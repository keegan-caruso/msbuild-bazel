"""Verify a Bazel-built application actually uses its source-built runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('workspace', type=Path)
p.add_argument('report', type=Path)
a = p.parse_args()
w = a.workspace.resolve()
a.report.parent.mkdir(parents=True, exist_ok=True)
manifest = json.loads((w/'subset.json').read_text())
assert manifest['sourceOnly'] and not manifest['installed']
host = (w/'bazel-bin/runtime/tree.layout').resolve()
framework = 'shared/Microsoft.NETCore.App/'+manifest['frameworkVersion']
expected = {}
for name, label in manifest['managed'].items():
    package, target = label.removeprefix('//').split(':')
    expected[framework+'/'+name] = w/'bazel-bin'/package/(target+'.runtime')/name
for name, label in manifest['native'].items():
    package, _ = label.removeprefix('//').split(':')
    expected[manifest['nativePaths'][name]] = w/'bazel-bin'/package/'runtime.generated'/name
expected['probe/Probe.dll'] = w/'bazel-bin/load_probe/probe.runtime/Probe.dll'
assert not manifest.get('private'), 'The ordinary app host must not include test dependencies'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


actual = {str(path.relative_to(host)): sha(path) for path in host.rglob('*')
          if path.is_file() and (path.suffix in ['.dll', '.so'] or path.name == 'dotnet')}
assert actual == {name: sha(path) for name, path in expected.items()}, 'Host differs from source producers'
# Use the Bazel launcher, including its runtime selection and runfiles wiring.
result = subprocess.run([w/'bazel-bin/app/app', '--describe-runtime'], cwd=w,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
a.report.with_suffix('.log').write_text(result.stdout)
assert result.returncode == 0, result.stdout
observed = json.loads(next(line.removeprefix('RUNTIME=') for line in result.stdout.splitlines()
                           if line.startswith('RUNTIME=')))
assert Path(observed['corelib']).resolve() == host/framework/'System.Private.CoreLib.dll'
loaded = set()
for row in observed['files']:
    path = Path(row['path']).resolve()
    if path.is_relative_to(host):
        relative = str(path.relative_to(host))
        assert row['sha256'].lower() == actual[relative], relative
        loaded.add(path.name)
    elif path.suffix == '.dll':
        # The launcher stages the application in a disposable execution directory.
        assert path.name == 'App.dll' and row['sha256'].lower() == sha(w/'bazel-bin/app/app.runtime/App.dll'), path
    else:
        assert path.name not in set(manifest['native']) | set(manifest['excludedRuntimeComponents']), path
required = set(manifest['native']) | {'System.Private.CoreLib.dll', 'System.Text.Json.dll',
                                    'System.IO.Compression.dll', 'System.Security.Cryptography.dll'}
assert required <= loaded, sorted(required-loaded)
# Run directly with no installed SDK, build checkout or package cache mounted.
# OS libraries are the explicit platform boundary for this Linux qualification.
isolated = subprocess.run([w/'native/bwrap', '--die-with-parent', '--unshare-all', '--new-session',
                           '--cap-drop', 'ALL', '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib',
                           '--ro-bind', '/etc', '/etc', '--proc', '/proc', '--dev', '/dev',
                           '--tmpfs', '/tmp', '--dir', '/opt', '--ro-bind', host, '/runtime',
                           '--ro-bind', (w/'bazel-bin/app/app.runtime').resolve(), '/app',
                           '--clearenv', '--setenv', 'DOTNET_ROOT', '/missing-sdk',
                           '--setenv', 'DOTNET_MULTILEVEL_LOOKUP', '1', '--',
                           '/runtime/dotnet', '/app/App.dll', '--describe-runtime'],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
a.report.with_suffix('.isolated.log').write_text(isolated.stdout)
assert isolated.returncode == 0, isolated.stdout
isolated_observed = json.loads(next(line.removeprefix('RUNTIME=') for line in isolated.stdout.splitlines()
                                    if line.startswith('RUNTIME=')))
assert isolated_observed['corelib'] == '/runtime/'+framework+'/System.Private.CoreLib.dll'
isolated_loaded = set()
for row in isolated_observed['files']:
    path = Path(row['path'])
    if path.is_relative_to('/runtime'):
        assert row['sha256'].lower() == actual[str(path.relative_to('/runtime'))], path
        isolated_loaded.add(path.name)
    elif path.suffix == '.dll':
        assert str(path) == '/app/App.dll' and row['sha256'].lower() == sha(w/'bazel-bin/app/app.runtime/App.dll'), path
    else:
        assert path.name not in set(manifest['native']) | set(manifest['excludedRuntimeComponents']), path
assert required <= isolated_loaded, sorted(required-isolated_loaded)
# Removing CoreCLR must fail, even when an installed runtime is advertised.
with tempfile.TemporaryDirectory(prefix='source-host-control-', dir=a.report.parent) as temp:
    broken = Path(temp)/'host'
    shutil.copytree(host, broken, copy_function=os.link)
    (broken/framework/'libcoreclr.so').unlink()
    control = subprocess.run([broken/'dotnet', (w/'bazel-bin/app/app.runtime/App.dll').resolve()],
                             env=dict(os.environ, DOTNET_ROOT=os.environ['RULES_MSBUILD_DOTNET_ROOT'],
                                      DOTNET_MULTILEVEL_LOOKUP='1'),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
    a.report.with_suffix('.missing-coreclr.log').write_text(control.stdout)
    assert control.returncode != 0 and 'Could not resolve CoreCLR path' in control.stdout, control.stdout
a.report.write_text(json.dumps(dict(framework=observed['framework'], binaryHashes=actual,
                                    missingCoreClrExitCode=control.returncode,
                                    isolatedLoadedSourceComponents=sorted(isolated_loaded), sdkAbsentExecution=True,
                                    loadedSourceComponents=sorted(loaded), observedFiles=observed['files']), indent=2)+'\n')
print('Verified source-built runtime and app execution:', len(loaded), 'loaded source components')
