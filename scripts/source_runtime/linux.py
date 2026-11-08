"""Native Linux ARM64 setup; all build products remain ordinary Bazel outputs."""
import fcntl
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import time

from .common import ROOT, digest, read_recipe, rules_identity, run, save, owned_output
from .acquisition import acquire_source
from .native import prepare_inputs

PREPARE = ROOT / 'tests/graph_build/upstream'


def launcher(path, bazelisk, registry, repository_cache, cache_url, distdir=None):
    # Helpers call the repository launcher. Its explicit Bazelisk override keeps
    # common acquisition/cache options on every nested Bazel invocation as well.
    options = []
    if registry:
        options.append('--registry=' + registry)
    if repository_cache:
        options.append('--repository_cache=' + str(repository_cache))
    if distdir:
        options.append('--distdir=' + str(distdir))
    if cache_url:
        options += ['--remote_cache=' + cache_url, '--remote_cache_async=false',
                    '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + cache_url]
    path.write_text('''#!/usr/bin/env bash
set -euo pipefail
args=()
added=0
for argument in "$@"; do
    args+=("$argument")
    case "$argument" in
        build|run|test|cquery|aquery|query|fetch)
            if [[ "$added" == 0 ]]; then args+=(''' + shlex.join(options) + '''); added=1; fi ;;
    esac
done
exec ''' + shlex.quote(str(bazelisk)) + ''' "${args[@]}"
''')
    path.chmod(0o755)


def build_command(base, action, arguments=()):
    state = json.loads((base / 'setup.json').read_text())
    workspace = Path(state['workspace'])
    env = dict(os.environ, **state['environment'])
    command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--nosystem_rc', '--nohome_rc', '--noworkspace_rc',
               '--output_base=' + str(base / 'bazel'), action]
    if action == 'run':
        command += ['//:app', '--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing', '--', *arguments]
    elif action == 'test':
        command += ['//:app_test', '//:runtime_test', '--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing', '--nocache_test_results', '--test_output=errors']
    else:
        command += ['//:app', '//:runtime_package', '--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing']
    return command, workspace, env


def setup(args):
    if platform.system() != 'Linux' or platform.machine() != 'aarch64':
        raise ValueError('Source-runtime builds require native Linux ARM64')
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if release.get('ID', '').strip('"') != 'ubuntu' or release.get('VERSION_ID', '').strip('"') != '22.04':
        raise ValueError('Use the supplied Ubuntu 22.04 native build image')
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    budget_kib = sum(int(memory[name].split()[0]) for name in ['MemTotal', 'SwapTotal'])
    if budget_kib < 7.5 * 1024**2:
        raise ValueError('The full runtime graph needs an 8 GiB memory budget (RAM plus swap)')
    if not args.native_toolchain and not shutil.which('dpkg-deb'):
        raise ValueError('Native package assembly requires dpkg-deb; use containers/runtime-demo.Dockerfile')
    base = args.output.expanduser().resolve()
    state = owned_output(base, args.resume, 'linux-source-runtime')
    if state:
        for name, value in state['options'].items():
            if getattr(args, name) is None and value is not None:
                setattr(args, name, Path(value) if name in ['repository_cache', 'native_toolchain', 'sandbox', 'host_space_path'] else value)
    if bool(args.native_toolchain) != bool(args.sandbox):
        raise ValueError('Provide --native-toolchain and --sandbox together')
    recipe = read_recipe()
    identity = dict(recipe=recipe, rulesSha256=rules_identity(), registry=args.registry, cacheUrl=args.cache_url,
                    nativePackagesSha256=digest(ROOT/'tests/runtime/native-packages.json') if not args.native_toolchain else None,
                    nativeToolchainSha256=digest(args.native_toolchain) if args.native_toolchain else None,
                    sandboxSha256=digest(args.sandbox) if args.sandbox else None,
                    repositoryCache=str(args.repository_cache.resolve()) if args.repository_cache else None)
    state_path = base / 'setup.json'
    with (base / 'setup.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if state:
            if state['identity'] != identity:
                raise ValueError('Setup inputs changed; use a fresh output directory')
        else:
            state = dict(version=1, kind='linux-source-runtime', identity=identity, completed=[], stages=[], ready=False,
                options={name: str(getattr(args, name)) if getattr(args, name) is not None else None for name in
                    ['registry', 'cache_url', 'repository_cache', 'native_toolchain', 'sandbox', 'host_space_path']})
        save(state_path, state)
        evidence = base / 'reports'
        evidence.mkdir(exist_ok=True)
        free_path = args.host_space_path or base
        def stage(name, command, cwd=None):
            if name in state['completed']:
                return
            if shutil.disk_usage(free_path).free < 12 * 1024**3:
                raise ValueError('At least 12 GiB physical host headroom is required')
            print('Source runtime: ' + name, flush=True)
            start = time.monotonic()
            with (evidence / (name + '.log')).open('w') as log:
                run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
            state['stages'].append(dict(name=name, seconds=time.monotonic()-start))
            state['completed'].append(name)
            save(state_path, state)
            subprocess.run(['fstrim', '/'], capture_output=True)
        sdk = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT / '.tools/dotnet')).resolve()
        bazelisk = Path(os.environ.get('RULES_MSBUILD_BAZELISK', ROOT / '.tools/bin/bazelisk')).resolve()
        for name, executable in [('RULES_MSBUILD_DOTNET_ROOT', sdk/'dotnet'), ('RULES_MSBUILD_BAZELISK', bazelisk)]:
            if name in os.environ and not executable.is_file():
                raise ValueError(name + ' points to a missing bootstrap tool: ' + str(executable))
        if not (sdk / 'dotnet').is_file() or not bazelisk.is_file():
            run(['bash', ROOT / 'scripts/setup.sh', '--toolchain-only'])
        wrapper = base / 'bazelisk.sh'
        distdir = base / 'downloads/nuget-dist'
        distdir.mkdir(parents=True, exist_ok=True)
        launcher(wrapper, bazelisk, args.registry, args.repository_cache, args.cache_url, distdir)
        env = dict(os.environ, RULES_MSBUILD_DOTNET_ROOT=str(sdk), RULES_MSBUILD_BAZELISK=str(wrapper),
                   RULES_MSBUILD_BAZEL=str(ROOT / 'scripts/bazel-launcher.sh'),
                   USE_BAZEL_VERSION='9.3.0', BAZELISK_HOME=os.environ.get('BAZELISK_HOME', str(ROOT / '.cache/bazelisk')))
        if args.repository_cache:
            env['RULES_MSBUILD_TEST_REPOSITORY_CACHE'] = str(args.repository_cache.resolve())
        if args.cache_url:
            env['RULES_MSBUILD_PROJECT_CACHE_URL'] = args.cache_url
        else:
            env.pop('RULES_MSBUILD_PROJECT_CACHE_URL', None)
            env.pop('RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', None)
        state['environment'] = {key: value for key, value in env.items() if key in ['RULES_MSBUILD_DOTNET_ROOT',
            'RULES_MSBUILD_BAZELISK','RULES_MSBUILD_BAZEL','RULES_MSBUILD_TEST_REPOSITORY_CACHE','RULES_MSBUILD_PROJECT_CACHE_URL','USE_BAZEL_VERSION','BAZELISK_HOME']}
        save(state_path, state)
        stage('tools', ['bash', ROOT / 'scripts/check.sh', '--toolchain-only'])
        archive = acquire_source(base, recipe['source'], env, args.source_archive)
        managed, native = base / 'managed', base / 'native'
        if 'managed' not in state['completed'] and managed.exists():
            if not args.resume:
                raise ValueError('Partial managed preparation requires --resume')
            # Resume retained, source-verified locks after an interrupted qualification.
            # Earlier failures have no published package inventory and can be retried.
            if not (managed / 'source/nuget.lock.json').exists() or (managed / 'workspace').exists():
                shutil.rmtree(managed)
        managed_command = [sys.executable, PREPARE / 'runtime_downloaded_prepare.py', archive, managed,
                           '--slice=runtime-product', '--evaluation-cache-mb=1024', '--nuget-http-cache=' + str(base/'downloads/nuget-http'), '--distdir=' + str(distdir), '--sdk-archive=' + str(ROOT / 'examples/source-runtime-app/source.json')]
        if args.cache_url:
            managed_command.append('--qualification-cache')
        if (managed / 'source/nuget.lock.json').exists() and not (managed / 'workspace').exists():
            managed_command.append('--resume')
        stage('managed', managed_command)
        if 'native' not in state['completed']:
            if native.exists():
                if not args.resume:
                    raise ValueError('Partial native declarations require --resume')
                shutil.rmtree(native)
            prepare_inputs(native, archive, args.native_toolchain, args.sandbox)
            state['completed'].append('native')
            save(state_path,state)
        workspace = base / 'workspace'
        state['workspace'] = str(workspace)
        if 'application' not in state['completed']:
            # Publish into a separate owned consumer. Interrupted composition cannot
            # corrupt the completed managed preparation used by --resume.
            if workspace.exists():
                shutil.rmtree(workspace)
            shutil.copytree(managed / 'workspace', workspace)
        stage('application', [sys.executable, PREPARE / 'runtime_application.py', workspace, native])
        command, cwd, _ = build_command(base, 'build')
        # The driver runs from the prepared source workspace, never from this repo.
        stage('build', command, cwd=cwd)
        command, cwd, _ = build_command(base, 'test')
        stage('verify', command, cwd=cwd)
        package = base/'runtime-linux-arm64.tar.gz'
        shutil.copyfile(workspace/'bazel-bin/runtime_package.tar.gz', package.with_suffix('.partial'))
        package.with_suffix('.partial').replace(package)
        state['archive'] = str(package)
        state['ready'] = True
        save(state_path, state)
        (base/'run.sh').write_text('#!/usr/bin/env bash\nset -euo pipefail\nexec ' + shlex.join([sys.executable, str(ROOT/'scripts/setup-source-runtime.py'), str(base), '--run', '--']) + ' "$@"\n')
        print('Runtime package: ' + str(package), flush=True)
        print('Ready. Run: bash ' + shlex.quote(str(base/'run.sh')) + ' --describe-runtime', flush=True)
