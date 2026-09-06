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


def action(request):
    execroot = Path.cwd()
    output = (execroot / request['output']).absolute()
    output.mkdir(parents=True, exist_ok=True)
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
    (output / 'build.log').write_text(process.stdout)
    observed = dict(project=project, workspace=str(workspace), command=command,
                    returncode=process.returncode, compiledProjects=re.findall(r'SPIKE_COMPILE:(\w+)', process.stdout),
                    replayHits=re.findall(r'SPIKE_REPLAY_HIT:(.*)', process.stdout),
                    sharedSources=[str(p.relative_to(workspace)) for p in (workspace / 'Shared').glob('*.cs')])
    (output / 'action.json').write_text(json.dumps(observed, indent=2))
    print(process.stdout)
    if process.returncode:
        raise RuntimeError(f'MSBuild {project} failed with {process.returncode}')
    if observed['compiledProjects'] != [project]:
        raise RuntimeError('unexpected project compilation: ' + str(observed['compiledProjects']))
    if project == 'App' and observed['replayHits'] != ['Shared']:
        raise RuntimeError('App did not replay Shared')
    manifest = []
    folders = ('Shared/bin', 'Shared/obj/Release') if project == 'Shared' else ('App/bin',)
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    action(json.loads(args.request.read_text()))
