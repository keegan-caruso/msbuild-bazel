#!/usr/bin/env python3
"""Create a seeded runtime CI demo on an Apple silicon Mac with Apple Container.

Cold setup downloads pinned sources/tools, qualifies 481 compilations, builds the
source runtime and executes eight suites. --resume reuses only completed stages
with identical inputs. --run executes the independent demo after setup.
"""
import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import uuid
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PREPARE = 'tests/graph_build/upstream/runtime_demo_prepare.py'
CACHE_IMAGE = 'docker.io/buchgr/bazel-remote-cache@sha256:8109f1f39eb17d898cf51e08b41e4eabaaaeb1f584c2f22c1be45b7568fcc512'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def call(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def inspect(name):
    result = subprocess.run(['container', 'inspect', name], capture_output=True, text=True)
    if result.returncode:
        # Distinguish a missing container from a stopped/unavailable engine.
        inventory = json.loads(subprocess.check_output(['container', 'list', '-a', '--format', 'json'], text=True))
        assert not any(row.get('id') == name or row.get('configuration', {}).get('id') == name for row in inventory), result.stderr
        return None
    return json.loads(result.stdout)[0]


def snapshot(destination):
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    names = set(filter(None, tracked)) | {PREPARE, 'scripts/setup-runtime-demo.py', 'containers/runtime-demo.Dockerfile'}
    with tarfile.open(destination, 'w') as archive:
        def normalize(member):
            member.uid = member.gid = member.mtime = 0
            member.uname = member.gname = ''
            return member
        for name in sorted(names):
            path = ROOT / name
            assert path.is_file() and not path.is_symlink(), name
            archive.add(path, arcname=name, recursive=False, filter=normalize)
    return digest(destination)


def cache_address(row):
    return str(ipaddress.ip_interface(row['status']['networks'][0]['ipv4Address']).ip)


def set_cache_host(name, address):
    # Keep the action environment URL stable if Apple Container reallocates IPs.
    program = '''from pathlib import Path
import sys
p=Path('/etc/hosts')
lines=[line for line in p.read_text().splitlines() if not line.endswith('# rules-msbuild-runtime-demo')]
lines.append(sys.argv[1]+' runtime-demo-cache # rules-msbuild-runtime-demo')
p.write_text('\\n'.join(lines)+'\\n')
'''
    call('container', 'exec', name, 'python3', '-c', program, address)


def save_state(path, state):
    temporary = path.with_suffix('.partial')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(path)


def transfer_identity(output, state):
    assert state['ready'] and 'transfer' in state['completed'], 'Complete setup before archiving its producer'
    rules = digest(output / 'rules.tar')
    inputs = digest(output / 'inputs.tar.gz')
    assert rules == state['rulesSha256'], 'Frozen rules archive changed'
    assert inputs == json.loads((output / 'transfer.json').read_text())['inputsSha256'], 'Input checkpoint changed'
    return dict(producer=state['producer'], image=state['image'], rulesSha256=rules,
        inputsSha256=inputs, seedSha256=digest(output / 'seed.json'))


def verify_producer(output, state):
    row = inspect(state['producer'])
    if row is None:
        assert state.get('producerArchive'), 'Producer missing without a verified archive; use --archive-producer before deletion'
        assert state['producerArchive'] == transfer_identity(output, state), 'Archived producer inputs changed'
    else:
        assert row['configuration']['labels'].get('rules-msbuild.demo') == state['id'], 'Producer ownership differs'
        assert row['configuration']['image']['descriptor']['digest'] == state['image'].split('@', 1)[1], 'Producer image differs'
        assert row['status']['state'] == 'stopped', 'Stop this setup\'s producer before running the consumer'
    return row


def archive_producer(output, state):
    row = verify_producer(output, state)
    if row is not None:
        state['producerArchive'] = transfer_identity(output, state)
        # Persist proof before deletion so an interrupted host call can resume.
        save_state(output / 'setup.json', state)
        call('container', 'delete', state['producer'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='new owned setup/state directory; retain it for resume and run')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--image', help='reuse an immutable Ubuntu 22.04 ARM64 image; default builds the native demo image')
    parser.add_argument('--cache-url', help='use an existing unauthenticated HTTP(S) cache instead of creating one')
    parser.add_argument('--prepared-inputs', type=Path, help='optional source-only checkpoint emitted by runtime_demo_prepare.py pack')
    parser.add_argument('--prepared-sha256', help='required digest for --prepared-inputs')
    parser.add_argument('--run', type=str, metavar='FRESH_GUEST_DIRECTORY', help='run an already prepared demo')
    parser.add_argument('--body-edit', action='store_true', help='with --run: also rehearse a unique body edit')
    parser.add_argument('--test-cache', choices=['yes', 'no'], help='new setup default yes: recover test results; no forces actual tests. With --run, override the saved policy')
    parser.add_argument('--archive-producer', action='store_true', help='verify retained inputs/seed, then delete the stopped producer; consumer runs remain supported')
    args = parser.parse_args()
    assert platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Requires an Apple silicon Mac'
    assert shutil.which('container') and shutil.which('git'), 'Install Apple Container and Git first'
    assert not args.body_edit or args.run
    assert not args.archive_producer or not (args.run or args.resume or args.image or args.cache_url or args.prepared_inputs or args.prepared_sha256 or args.test_cache)
    output = args.output.expanduser().resolve()
    state_path = output / 'setup.json'
    if args.run or args.archive_producer:
        with (output / 'setup.lock').open('a+') as setup_lock:
            fcntl.flock(setup_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            state = json.loads(state_path.read_text())
            assert state['version'] == 1 and state['ready'], 'Setup has not completed; rerun with --resume'
            if args.archive_producer:
                archive_producer(output, state)
                print('Producer archived and deleted; keep this setup directory for consumer runs.', flush=True)
                return
            verify_producer(output, state)
            policy = args.test_cache or state['options'].get('testCache', 'no')
            if policy == 'yes':
                seed = json.loads((output / 'seed.json').read_text())
                assert seed.get('testCachePolicy') == 'yes', 'This setup did not seed cached tests; create a fresh setup with --test-cache=yes'
            if state.get('cache'):
                cache = inspect(state['cache'])
                assert cache and cache['configuration']['labels'].get('rules-msbuild.demo') == state['id']
                assert cache['configuration']['image']['descriptor']['digest'] == state.get('cacheImage', CACHE_IMAGE).split('@', 1)[1]
                if cache['status']['state'] != 'running':
                    call('container', 'start', state['cache'])
                address = cache_address(inspect(state['cache']))
            consumer = inspect(state['consumer'])
            assert consumer and consumer['configuration']['labels'].get('rules-msbuild.demo') == state['id']
            assert consumer['configuration']['image']['descriptor']['digest'] == state['image'].split('@', 1)[1]
            if consumer['status']['state'] != 'running':
                call('container', 'start', state['consumer'])
            if state.get('cache'):
                set_cache_host(state['consumer'], address)
            call('container', 'exec', state['consumer'], 'bash', '/demo/rehearse.sh', args.run,
                '--test-cache=' + policy,
                *(['--require-test-recovery'] if policy == 'yes' and not args.body_edit else []),
                *(['--body-edit'] if args.body_edit else []))
            return

    assert bool(args.prepared_inputs) == bool(args.prepared_sha256), 'Supply checkpoint and SHA-256 together'
    if args.image:
        assert re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}', args.image), 'Use an immutable image digest'
    if args.cache_url:
        url = urlsplit(args.cache_url)
        assert url.scheme in ['http', 'https'] and url.hostname and not url.username and not url.password
    if args.prepared_inputs:
        assert re.fullmatch('[a-f0-9]{64}', args.prepared_sha256)
        assert digest(args.prepared_inputs) == args.prepared_sha256
    if args.resume:
        state = json.loads(state_path.read_text())
        assert state['version'] == 1
        for attribute, key in [('image', 'image'), ('cache_url', 'cacheUrl'), ('prepared_sha256', 'preparedSha256')]:
            supplied = getattr(args, attribute)
            assert supplied is None or supplied == state['options'][key], 'Setup options changed; use a fresh output'
            setattr(args, attribute, state['options'][key])
        assert args.test_cache is None or args.test_cache == state['options'].get('testCache', 'no'), 'Setup test policy changed; use a fresh output'
        if args.prepared_sha256 and args.prepared_inputs is None:
            args.prepared_inputs = output / 'prepared.tar.gz'
    else:
        assert not output.exists(), 'Use an absent output directory or --resume'
        reserve = 32 if args.prepared_inputs and args.cache_url else 60
        existing = output.parent
        while not existing.exists():
            existing = existing.parent
        assert shutil.disk_usage(existing).free >= reserve * 1024**3, f'Setup needs {reserve} GiB free; no resources were created'
        output.mkdir(parents=True, mode=0o700)
        identity = uuid.uuid4().hex[:10]
        prefix = 'msbuild-runtime-demo-' + identity
        state = dict(version=1, id=identity, options=dict(image=args.image, cacheUrl=args.cache_url, preparedSha256=args.prepared_sha256, testCache=args.test_cache or 'yes'),
            cacheImage=CACHE_IMAGE, producer=prefix + '-producer', consumer=prefix + '-consumer', cache=None if args.cache_url else prefix + '-cache', completed=[], ready=False)

    setup_lock = (output / 'setup.lock').open('a+')
    fcntl.flock(setup_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def save():
        save_state(state_path, state)

    def stage(name, action):
        if name not in state['completed']:
            print('Setup: ' + name, flush=True)
            action()
            state['completed'].append(name)
            save()

    save()
    if state.get('rulesSha256'):
        assert digest(output / 'rules.tar') == state['rulesSha256'], 'Frozen rules archive changed'
    else:
        temporary_rules = output / 'rules.partial.tar'
        current = snapshot(temporary_rules)
        temporary_rules.replace(output / 'rules.tar')
        state['rulesSha256'] = current
        save()
    if state.get('producerArchive'):
        verify_producer(output, state)
    if Path(__file__).resolve() != output / 'control.py':
        shutil.copyfile(Path(__file__).resolve(), output / 'control.py')
    if args.prepared_inputs and not (output / 'prepared.tar.gz').exists():
        try:
            os.link(args.prepared_inputs, output / 'prepared.tar.gz')
        except OSError:
            shutil.copyfile(args.prepared_inputs, output / 'prepared.tar.gz')
    if args.prepared_inputs:
        assert digest(output / 'prepared.tar.gz') == args.prepared_sha256

    def image():
        if args.image:
            state['image'] = args.image
            return
        context = output / 'image'
        context.mkdir(exist_ok=True)
        with tarfile.open(output / 'rules.tar') as archive:
            (context / 'Dockerfile').write_bytes(archive.extractfile('containers/runtime-demo.Dockerfile').read())
        tag = 'rules-msbuild-runtime-demo:' + state['id']
        with (output / 'image-build.log').open('w') as log:
            call('container', 'build', '--platform', 'linux/arm64', '--cpus', '4', '--memory', '4G', '--tag', tag, context,
                stdout=log, stderr=subprocess.STDOUT)
        record = json.loads(subprocess.check_output(['container', 'image', 'inspect', tag], text=True))[0]
        (output / 'image.json').write_text(json.dumps(record, indent=2) + '\n')
        config = record['configuration']
        state['image'] = config['name'].rsplit(':', 1)[0] + '@' + config['descriptor']['digest']
        call('container', 'image', 'tag', tag, state['image'])
    stage('image', image)

    def ensure(name, memory, cache=False):
        row = inspect(name)
        if row:
            expected = state.get('cacheImage', CACHE_IMAGE) if cache else state['image']
            assert row['configuration']['image']['descriptor']['digest'] == expected.split('@', 1)[1], 'Container image differs'
            assert row['configuration']['labels'].get('rules-msbuild.demo') == state['id'], 'Container ownership differs'
            if row['status']['state'] != 'running':
                call('container', 'start', name)
            return
        command = ['container', 'run', '-d', '--arch', 'arm64', '--name', name, '--cpus', '2' if cache else '4',
            '--memory', memory, '--label', 'rules-msbuild.demo=' + state['id']]
        if cache:
            command += ['--user', '0', state.get('cacheImage', CACHE_IMAGE), '--http_address=:8080', '--dir=/data', '--max_size=16']
        else:
            command += ['--init', '--cap-add', 'SYS_ADMIN', '--masked-path', 'NONE', '--read-only-path', 'NONE',
                '--volume', str(output) + ':/host:ro', state['image'], 'sleep', 'infinity']
        call(*command)

    if state['cache']:
        ensure(state['cache'], '1G', cache=True)
        address = cache_address(inspect(state['cache']))
        state['cacheUrl'] = 'http://runtime-demo-cache:8080'
    else:
        state['cacheUrl'] = args.cache_url
    save()

    def install(name, config):
        ensure(name, '8G' if name == state['producer'] else '6G')
        if state['cache']:
            set_cache_host(name, address)
        call('container', 'exec', name, 'mkdir', '-p', '/demo/rules')
        call('container', 'exec', name, 'tar', '-xf', '/host/rules.tar', '-C', '/demo/rules')
        config_path = output / ('producer-config.json' if name == state['producer'] else 'consumer-config.json')
        config_path.write_text(json.dumps(config, indent=2) + '\n')
        call('container', 'cp', config_path, name + ':/demo/config.json')
        packages = subprocess.check_output(['container', 'exec', name, 'dpkg-query', '-W', '-f=${Package}\t${Version}\n'], text=True)
        (output / (name + '-packages.txt')).write_text(packages)

    config = dict(rulesSha256=state['rulesSha256'], image=state['image'], cacheUrl=state['cacheUrl'], preparedSha256=args.prepared_sha256)
    if 'testCache' in state['options']:
        config['testCache'] = state['options']['testCache']
    def producer():
        install(state['producer'], config)
        with (output / 'producer.log').open('a') as log:
            call('container', 'exec', state['producer'], 'python3', '/demo/rules/' + PREPARE, 'producer', stdout=log, stderr=subprocess.STDOUT)
    stage('producer', producer)
    def transfer():
        for name in ['seed.json', 'inputs.tar.gz', 'transfer.json']:
            call('container', 'cp', state['producer'] + ':/demo/' + name, output / name)
        assert digest(output / 'inputs.tar.gz') == json.loads((output / 'transfer.json').read_text())['inputsSha256']
    stage('transfer', transfer)
    row = inspect(state['producer'])
    if row and row['status']['state'] == 'running':
        call('container', 'stop', state['producer'])

    def consumer():
        config['inputsSha256'] = digest(output / 'inputs.tar.gz')
        install(state['consumer'], config)
        with (output / 'consumer.log').open('a') as log:
            call('container', 'exec', state['consumer'], 'python3', '/demo/rules/' + PREPARE, 'consumer', stdout=log, stderr=subprocess.STDOUT)
        script = '''#!/usr/bin/env bash
set -euo pipefail
export RULES_MSBUILD_DOTNET_ROOT=/demo/rules/.tools/dotnet
export RULES_MSBUILD_BAZELISK=/demo/rules/.tools/bin/bazelisk
export RULES_MSBUILD_TEST_REPOSITORY_CACHE=/demo/repository-cache
export USE_BAZEL_VERSION=9.3.0
exec bash /demo/rules/tests/graph_build/upstream/runtime_ci_demo.sh /demo/consumer/workspace /demo/seed.json "$1" ''' + shlex.quote(state['cacheUrl']) + ''' /host "${@:2}"
'''
        (output / 'guest-run.sh').write_text(script)
        call('container', 'cp', output / 'guest-run.sh', state['consumer'] + ':/demo/rehearse.sh')
    stage('consumer', consumer)
    state['ready'] = True
    save()
    run = ['python3', str(output / 'control.py'), str(output), '--run']
    (output / 'run.sh').write_text('#!/usr/bin/env bash\nset -euo pipefail\nexec ' + shlex.join(run) + ' "$@"\n')
    print('Ready. Consumer and cache retained.\nRun: bash ' + shlex.quote(str(output / 'run.sh')) + ' /tmp/runtime-demo-1', flush=True)


if __name__ == '__main__':
    main()
