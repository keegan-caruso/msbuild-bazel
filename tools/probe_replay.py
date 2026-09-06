"""Public API replay experiment; retains commands, logs, bundles and report."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from spike import DOTNET, ROOT


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifacts(bundle, workspace, capture=False):
    if capture:
        manifest = []
        for folder in ('Shared/bin', 'Shared/obj/Release'):
            for source in sorted((workspace / folder).rglob('*')):
                if source.is_file():
                    relative = source.relative_to(workspace).as_posix()
                    destination = bundle / 'artifacts' / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    manifest.append(dict(path=relative, size=source.stat().st_size, sha256=digest(source)))
        (bundle / 'artifacts.json').write_text(json.dumps(manifest, indent=2))
        return
    manifest = json.loads((bundle / 'artifacts.json').read_text())
    if not manifest:
        raise ValueError('dependency artifacts empty')
    for entry in manifest:
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.parts[:2] not in [('Shared', 'bin'), ('Shared', 'obj')]:
            raise ValueError('dependency artifact path invalid')
        source = bundle / 'artifacts' / relative
        if not source.is_file() or source.stat().st_size != entry['size'] or digest(source) != entry['sha256']:
            raise ValueError('dependency artifact missing or corrupt: ' + str(relative))
    for entry in manifest:
        destination = workspace / entry['path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle / 'artifacts' / entry['path'], destination)


def probe(output):
    output.mkdir(parents=True, exist_ok=False)
    report = dict(schemaVersion=1, platform=platform.platform(), architecture=platform.machine(), cases={})

    def run(name, workspace, args, extra=None):
        env = os.environ.copy()
        env.update(DOTNET_ROOT=str(DOTNET.parent), DOTNET_CLI_HOME=str(output / 'dotnet-home'),
                   NUGET_PACKAGES=str(workspace / '.nuget/packages'), DOTNET_NOLOGO='1',
                   DOTNET_CLI_TELEMETRY_OPTOUT='1', MSBUILDDISABLENODEREUSE='1')
        env.update(extra or {})
        command = [str(DOTNET), *args]
        result = subprocess.run(command, cwd=workspace, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        log = output / (name + '.log')
        log.write_text(result.stdout)
        observed = dict(command=command, cwd=str(workspace), environment={key: env[key] for key in
                        ('DOTNET_ROOT', 'DOTNET_CLI_HOME', 'NUGET_PACKAGES')},
                        replayEnvironment=extra or {},
                        requestedTargets=re.findall(r'SPIKE_REPLAY_REQUEST:(.*)', result.stdout),
                        replayHits=re.findall(r'SPIKE_REPLAY_HIT:(.*)', result.stdout),
                        returncode=result.returncode, log=str(log),
                        compiledProjects=re.findall(r'SPIKE_COMPILE:(\w+)', result.stdout))
        report['cases'][name] = observed
        (output / 'report.json').write_text(json.dumps(report, indent=2))
        return observed

    def require(result):
        if result['returncode']:
            raise RuntimeError('command failed; see ' + result['log'])

    require(run('pluginBuild', ROOT, ['build', str(ROOT / 'tools/ReplayPlugin'), '-c', 'Release', '--nologo']))
    version_env = dict(os.environ, DOTNET_CLI_HOME=str(output / 'dotnet-home'), DOTNET_NOLOGO='1')
    report['sdkVersion'] = subprocess.check_output([str(DOTNET), '--version'], cwd=ROOT, env=version_env, text=True).strip()
    report['engineVersion'] = subprocess.check_output([str(DOTNET), 'msbuild', '-version', '-nologo'], cwd=ROOT, env=version_env, text=True).strip()
    plugin = ROOT / 'tools/ReplayPlugin/bin/Release/net10.0/ReplayPlugin.dll'
    bundle = output / 'bundle'
    bundle.mkdir()

    def setup(name):
        workspace = output / name
        shutil.copytree(ROOT / 'tests/fixtures/two-projects', workspace)
        require(run(name + '-restore', workspace, ['msbuild', 'dirs.proj', '-t:Restore', '-p:Configuration=Release', '-nologo']))
        for project in ('Shared', 'App'):
            shutil.copytree(workspace / project / 'obj', output / (name + '-restore-state') / project)
        tree = ET.parse(workspace / 'Directory.Build.targets')
        ET.SubElement(ET.SubElement(tree.getroot(), 'ItemGroup'), 'ProjectCachePlugin', Include=str(plugin))
        tree.write(workspace / 'Directory.Build.targets')
        return workspace

    def clean(workspace):
        for project in ('Shared', 'App'):
            shutil.rmtree(workspace / project / 'bin', ignore_errors=True)
            shutil.rmtree(workspace / project / 'obj', ignore_errors=True)
            shutil.copytree(output / (workspace.name + '-restore-state') / project, workspace / project / 'obj')

    def build(name, workspace, mode='replay', target='Build'):
        if mode == 'replay':
            try:
                artifacts(bundle, workspace)
            except (ValueError, OSError) as error:
                log = output / (name + '.log')
                log.write_text(str(error))
                result = dict(returncode=1, log=str(log), compiledProjects=[], command=[], phase='artifact-validation')
                report['cases'][name] = result
                return result
        return run(name, workspace, ['msbuild', 'App/App.csproj', '-t:' + target,
                   '-p:Configuration=Release', '-graphBuild', '-isolateProjects', '-nodeReuse:false',
                   '-nologo', '-verbosity:normal'],
                   dict(SPIKE_REPLAY_WORKSPACE=str(workspace), SPIKE_REPLAY_BUNDLE=str(bundle), SPIKE_REPLAY_MODE=mode))

    def application(result, workspace, publish=False):
        path = workspace / 'App/bin/Release/net10.0'
        if publish:
            path /= 'publish'
        process = subprocess.run([str(DOTNET), str(path / 'App.dll')], text=True, capture_output=True, timeout=30)
        result.update(applicationReturncode=process.returncode, applicationOutput=process.stdout.strip(),
                      applicationCommand=[str(DOTNET), str(path / 'App.dll')], applicationError=process.stderr)

    producer = setup('producer')
    require(build('capture', producer, 'capture', 'Build;Publish'))
    artifacts(bundle, producer, capture=True)
    clean(producer)
    result = build('samePath', producer)
    require(result)
    application(result, producer)
    consumer = setup('consumer')
    shutil.rmtree(producer)
    report['producerAbsent'] = not producer.exists()
    result = build('relocated', consumer)
    require(result)
    application(result, consumer)
    clean(consumer)
    program = consumer / 'App/Program.cs'
    program.write_text(program.read_text().replace('app-v1', 'app-v2'))
    result = build('appEdit', consumer)
    require(result)
    application(result, consumer)
    clean(consumer)
    result = build('publish', consumer, target='Publish')
    require(result)
    application(result, consumer, publish=True)

    payload_path = bundle / 'results.json'
    original = payload_path.read_text()
    for name, field, value in [('missingPayload', None, None), ('missingTarget', 'targets', {}),
                               ('propertiesMismatch', 'properties', {'Configuration': 'Debug'}),
                               ('sdkMismatch', 'sdkVersion', '0'), ('engineMismatch', 'engineVersion', '0'),
                               ('schemaMismatch', 'schemaVersion', 999),
                               ('frameworkMismatch', 'targetFramework', 'net9.0'),
                               ('rootMismatch', 'rootMappings', {}),
                               ('missingPublishTarget', 'targets', None),
                               ('externalPath', 'targets', None)]:
        clean(consumer)
        payload = json.loads(original)
        if name == 'missingPayload':
            payload_path.unlink()
        else:
            if name == 'missingPublishTarget':
                del payload['targets']['GetCopyToPublishDirectoryItems']
            elif name == 'externalPath':
                payload['targets']['Build'][0]['spec'] = '/unsupported-external/Shared.dll'
            else:
                payload[field] = value
            payload_path.write_text(json.dumps(payload))
        result = build(name, consumer, target='Publish' if name == 'missingPublishTarget' else 'Build')
        payload_path.write_text(original)
        if result['returncode'] == 0 or result['compiledProjects']:
            raise RuntimeError('negative case did not reject dependency: ' + name)
    clean(consumer)
    manifest = json.loads((bundle / 'artifacts.json').read_text())
    missing = bundle / 'artifacts' / manifest[0]['path']
    contents = missing.read_bytes()
    missing.unlink()
    build('missingArtifact', consumer)
    missing.write_bytes(contents)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(output / 'report.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        probe(args.output.resolve())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
