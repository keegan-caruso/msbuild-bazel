"""One fixture project per Bazel action; never restores or downloads."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

TARGETS = ('GetTargetFrameworks;Build;GetNativeManifest;GetCopyToOutputDirectoryItems;'
           'GetTargetFrameworksWithPlatformForSingleTargetFramework;GetCopyToPublishDirectoryItems')


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage_packages(request, workspace, execroot):
    assets = json.loads((workspace / request['project'] / 'obj/project.assets.json').read_text())
    resolved = {key.lower(): value['path'] for key, value in assets['libraries'].items() if value['type'] == 'package'}
    manifest = {'schemaVersion': 1, 'packages': []}
    if request['package_manifest']:
        manifest = json.loads((execroot / request['package_manifest']).read_text())
    if manifest['schemaVersion'] != 1:
        raise ValueError('package manifest version mismatch')
    provided = {f"{p['id']}/{p['version']}".lower(): p['path'] for p in manifest['packages']}
    if provided != resolved:
        raise ValueError('package manifest does not match restore assets')
    project = ET.parse(workspace / request['project'] / (request['project'] + '.csproj'))
    for ref in project.getroot().iter('PackageReference'):
        version = ref.get('Version', '')
        if not version.startswith('[') or not version.endswith(']') or ',' in version:
            raise ValueError('package requires an exact inline version')
        if (ref.get('Include', '') + '/' + version[1:-1]).lower() not in resolved:
            raise ValueError('package reference differs from restored version')
    files = {entry['destination']: execroot / entry['source'] for entry in request['packages']}
    staged = []
    for package in manifest['packages']:
        for entry in package['files']:
            relative = Path(package['path']) / entry['path']
            if relative.is_absolute() or '..' in relative.parts or '\\' in str(relative):
                raise ValueError('package payload path invalid')
            source = files.get(relative.as_posix())
            if source is None or not source.is_file():
                raise ValueError('package payload missing: ' + str(relative))
            if source.stat().st_size != entry['size'] or sha256(source) != entry['sha256']:
                raise ValueError('package payload hash mismatch: ' + str(relative))
            staged.append((source, workspace / '.nuget/packages' / relative))
    if len(staged) != len(files):
        raise ValueError('package payload set mismatch')
    for source, target in staged:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return sorted(resolved)


def action(request):
    execroot = Path.cwd()
    if request.get('native_manifest'):
        manifest = json.loads((execroot / request['native_manifest']).read_text())
        entries = request['native_files']
        if manifest['schemaVersion'] != 1 or sorted(e['destination'] for e in entries) != sorted(manifest['files']):
            raise ValueError('native runtime closure declaration mismatch')
        for entry in entries:
            if not (execroot / entry['source']).is_file():
                raise ValueError('native runtime closure file missing: ' + entry['destination'])
    output = (execroot / request['output']).absolute()
    output.mkdir(parents=True, exist_ok=True)
    diagnostics = execroot / request['diagnostics']
    diagnostics.mkdir(parents=True, exist_ok=True)
    # Under the declared output so platform sandboxes allow writes. Scratch is
    # removed before success; only the bundle is returned to Bazel.
    scratch = Path(tempfile.mkdtemp(prefix='work-', dir=output))
    workspace = scratch / 'workspace'
    workspace.mkdir()
    project = request['project']
    dotnet = (execroot / request['dotnet']).resolve()
    plugin = (execroot / request['plugin']).resolve()
    if request['undeclared_probe']:
        # A relative execroot input that exists in the source checkout but is
        # omitted from the action inputs must not be visible in the sandbox.
        (execroot / request['undeclared_probe']).read_text()
    for source in request['sources']:
        target = workspace / source['destination']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(execroot / source['source'], target)
    for restore in request['restore']:
        state = json.loads((execroot / restore).read_text())
        for relative, contents in state.items():
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents.replace('${WORKSPACE}', str(workspace)).replace('${SDK}', str(dotnet.parent)))
    packages = stage_packages(request, workspace, execroot)
    # These are local evaluated properties, not global properties in the replay
    # identity. Both projects map their current action workspace identically.
    props = ET.parse(workspace / 'Directory.Build.props')
    group = ET.SubElement(props.getroot(), 'PropertyGroup')
    ET.SubElement(group, 'PathMap').text = str(workspace) + '=/_/workspace'
    ET.SubElement(group, 'Deterministic').text = 'true'
    # A copied fixture must not discover the enclosing checkout's Git metadata.
    ET.SubElement(group, 'EnableSourceControlManagerQueries').text = 'false'
    ET.SubElement(group, 'EnableSourceLink').text = 'false'
    props.write(workspace / 'Directory.Build.props')
    tree = ET.parse(workspace / 'Directory.Build.targets')
    ET.SubElement(ET.SubElement(tree.getroot(), 'ItemGroup'), 'ProjectCachePlugin', Include=str(plugin))
    tree.write(workspace / 'Directory.Build.targets')
    bundle = output
    if project == 'App':
        if not request['dependency']:
            raise ValueError('App requires a Shared dependency bundle')
        bundle = scratch / 'dependency'
        shutil.copytree(execroot / request['dependency'], bundle)
        manifest = json.loads((bundle / 'artifacts.json').read_text())
        if not manifest:
            raise ValueError('dependency artifacts empty')
        for entry in manifest:
            relative = Path(entry['path'])
            if relative.is_absolute() or '..' in relative.parts or relative.parts[:2] not in [('Shared', 'bin'), ('Shared', 'obj')]:
                raise ValueError('dependency artifact path invalid')
            source = bundle / 'artifacts' / relative
            if not source.is_file() or source.stat().st_size != entry['size'] or sha256(source) != entry['sha256']:
                raise ValueError('dependency artifact missing or corrupt')
        for entry in manifest:
            target = workspace / entry['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundle / 'artifacts' / entry['path'], target)
    env = dict(os.environ, DOTNET_ROOT=str(dotnet.parent),
               DOTNET_CLI_HOME=str(scratch / 'home'), NUGET_PACKAGES=str(workspace / '.nuget/packages'),
               DOTNET_NOLOGO='1', DOTNET_CLI_TELEMETRY_OPTOUT='1', MSBUILDDISABLENODEREUSE='1',
               TMPDIR=str(scratch), TMP=str(scratch), TEMP=str(scratch),
               SPIKE_REPLAY_MODE='capture' if project == 'Shared' else 'replay',
               SPIKE_REPLAY_WORKSPACE=str(workspace), SPIKE_REPLAY_BUNDLE=str(bundle))
    command = [str(dotnet), 'msbuild', f'{project}/{project}.csproj',
               '-t:' + (TARGETS if project == 'Shared' else 'Build'),
               '-p:Configuration=Release', '-graphBuild', '-isolateProjects',
               '-nodeReuse:false', '-nologo', '-verbosity:normal']
    process = subprocess.run(command, cwd=workspace, env=env, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    (diagnostics / 'build.log').write_text(process.stdout)
    observed = dict(project=project, workspace=str(workspace), command=command, packages=packages,
                    packageTargets=re.findall(r'SPIKE_PACKAGE_TARGET:(\w+)', process.stdout),
                    returncode=process.returncode, compiledProjects=re.findall(r'SPIKE_COMPILE:(\w+)', process.stdout),
                    replayHits=re.findall(r'SPIKE_REPLAY_HIT:(.*)', process.stdout),
                    sharedSources=[str(p.relative_to(workspace)) for p in (workspace / 'Shared').glob('*.cs')])
    (diagnostics / 'action.json').write_text(json.dumps(observed, indent=2))
    print(process.stdout)
    if process.returncode:
        raise RuntimeError(f'MSBuild {project} failed with {process.returncode}')
    if observed['compiledProjects'] != [project]:
        raise RuntimeError('unexpected project compilation: ' + str(observed['compiledProjects']))
    if project == 'App' and observed['replayHits'] != ['Shared']:
        raise RuntimeError('App did not replay Shared')
    manifest = []
    # Replay needs runtime outputs plus the reference assembly; SDK incremental
    # caches, generated source and absolute file lists are producer-private.
    folders = ('Shared/bin', 'Shared/obj/Release/net10.0/ref') if project == 'Shared' else ('App/bin',)
    for folder in folders:
        for source in sorted((workspace / folder).rglob('*')):
            if source.is_file():
                relative = source.relative_to(workspace).as_posix()
                target = output / 'artifacts' / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                manifest.append(dict(path=relative, size=source.stat().st_size, sha256=sha256(source)))
    (output / 'artifacts.json').write_text(json.dumps(manifest, indent=2))
    shutil.rmtree(scratch)
    for path in output.glob('graph-*.json'):
        shutil.move(path, diagnostics / path.name)
    # JSON object iteration order in MSBuild is not an output contract. Preserve
    # item order, but canonicalize object keys and the target-name set.
    results = output / 'results.json'
    if results.exists():
        payload = json.loads(results.read_text())
        payload['requestedTargets'] = sorted(payload['requestedTargets'])
        results.write_text(json.dumps(payload, sort_keys=True, indent=2) + '\n')
    for path in sorted(output.rglob('*'), reverse=True):
        path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
        os.utime(path, (0, 0))
    os.utime(output, (0, 0))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    action(json.loads(args.request.read_text()))
