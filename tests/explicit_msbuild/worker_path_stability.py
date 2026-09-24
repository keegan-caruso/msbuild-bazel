"""Fresh isolated workers must agree even when targets embed physical paths.

Run in the qualified Linux worker image; this deliberately bypasses action caches.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
runner = ROOT/'tools/ExplicitBuild/bin/Release/net10.0/ExplicitBuild.dll'
results = []
stable_paths = []
for index in range(2):
    with tempfile.TemporaryDirectory(prefix=f'path-control-{index}-') as directory:
        root = Path(directory)
        (root/'scratch').mkdir()
        (root/'Library.csproj').write_text('''<Project Sdk="Microsoft.NET.Sdk">
<PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>
<ItemGroup><AssemblyAttribute Include="System.Reflection.AssemblyMetadataAttribute">
<_Parameter1>PhysicalAssetPath</_Parameter1>
<_Parameter2>$(MSBuildProjectDirectory)/asset.txt</_Parameter2>
</AssemblyAttribute></ItemGroup></Project>''')
        (root/'Value.cs').write_text('public static class Value { public static int Get() => 7; }')
        request = dict(project=dict(source='Library.csproj', path='Library.csproj'),
            sources=[dict(source='Value.cs', path='Value.cs')], imports=[], items=[],
            dependencies=[], references=[], framework='net10.0', frameworkReferences=[],
            assembly='Library', executable=False, configuration='Release', properties={},
            defines=[], nullable='enable', languageVersion='latest', allowUnsafe=False,
            runtime='runtime', reference='reference/Library.dll', diagnostics='diagnostics',
            sdkVersion='10.0.400', runtimeManifest='', packages=[], declaredPackages=[],
            compilePackages=[], buildPackages=[], analyzerPackages=[])
        (root/'request.json').write_text(json.dumps(request))
        inputs = [dict(path=name, digest=base64.b64encode(hashlib.sha256((root/name).read_bytes()).hexdigest().encode()).decode())
                  for name in ['Library.csproj', 'Value.cs', 'request.json']]
        work = dict(arguments=['request.json'], inputs=inputs, requestId=1)
        result = subprocess.run([str(SDK/'dotnet'), str(runner), '--bazel-worker', '--persistent_worker'],
            cwd=root, input=json.dumps(work)+'\n', capture_output=True, text=True, timeout=120,
            env=dict(os.environ, TMPDIR=str(root/'scratch')))
        assert result.returncode == 0, result.stderr
        reply = json.loads(result.stdout)
        assert reply['exitCode'] == 0, reply['output']
        files = ['reference/Library.dll', 'runtime/Library.dll', 'runtime/Library.pdb']
        results.append({name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files})
        payload = (root/'runtime/Library.dll').read_bytes()
        stable_paths.append(b'/__rules_msbuild/in/' in payload and b'explicit-worker-' not in payload and str(root).encode() not in payload)
assert results[0] == results[1], results
assert all(stable_paths), 'Missing embedded stable physical path'
print(json.dumps(dict(freshWorkers=2, matching=results[0]), indent=2))
