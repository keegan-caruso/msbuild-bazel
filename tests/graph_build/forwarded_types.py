"""Qualify reviewed metadata-driven generation through sync and public graph rules."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path, help='new disposable Linux ARM64 directory')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    root = args.workspace.resolve()
    base = root.with_name(root.name + '-base')
    assert not base.exists()
    root.mkdir(parents=True, exist_ok=False)
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
    env = dict(os.environ)
    for key in ['RULES_MSBUILD_PROJECT_CACHE_URL', 'RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN']:
        env.pop(key, None)
    project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><DefaultItemExcludes>$(DefaultItemExcludes);request.txt</DefaultItemExcludes></PropertyGroup><ItemGroup><AdditionalFiles Include="types.txt" /><ForwardedType Include="$([System.IO.File]::ReadAllText(\'$(MSBuildProjectDirectory)/types.txt\'))"><Namespace>Qualification</Namespace></ForwardedType></ItemGroup><Import Project="Gen.targets" /></Project>'
    (root / 'Probe.csproj').write_text(project)
    (root / 'types.txt').write_text('Generated')
    target = '''<Project><Target Name="CreateCompileSourceForForwardedTypes" BeforeTargets="CoreCompile"><WriteLinesToFile File="$(IntermediateOutputPath)Forwarded.cs" Lines="@(ForwardedType->'namespace %(Namespace) { public class %(Identity) { } }')" Overwrite="true"/><ItemGroup><Compile Include="$(IntermediateOutputPath)Forwarded.cs"/><FileWrites Include="$(IntermediateOutputPath)Forwarded.cs"/></ItemGroup></Target></Project>'''
    (root / 'Gen.targets').write_text(target)
    (root / 'NuGet.Config').write_text('<configuration><packageSources><clear/></packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>')
    (root / 'packages').mkdir()
    (root / 'inputs.json').write_text(json.dumps(dict(Inputs=[], Packages=[])))
    mapping = dict(projectDefaults=dict(documents={'Gen.targets': dict(sha256=hashlib.sha256(target.encode()).hexdigest(),
        targets=['CreateCompileSourceForForwardedTypes'], tasks=[], inputs=[])}, evaluationItems=['ForwardedType']))
    (root / 'mapping.json').write_text(json.dumps(mapping))
    (root / 'MODULE.bazel').write_text('module(name="forwarded_types_fixture")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
        'local_path_override(module_name="rules_msbuild",path=' + json.dumps(str(ROOT)) + ')\n'
        'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
        'dotnet.sdk(name="dotnet",global_json="@rules_msbuild//:global.json")\n'
        'use_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
    command = [str(sdk / 'dotnet'), str(ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll'), str(root),
        str(sdk / 'sdk/10.0.400'), 'Probe.csproj', '--framework', 'net10.0', '--inputs', str(root / 'inputs.json'),
        '--runfiles', str(root / 'packages'), '--mappings', str(root / 'mapping.json')]
    env.update(DOTNET_ROOT=str(sdk), DOTNET_HOST_PATH=str(sdk / 'dotnet'))
    def sync(name, success):
        result = subprocess.run(command, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        root.with_name(root.name + '-' + name + '.log').write_text(result.stdout)
        if success:
            assert result.returncode == 0, result.stdout
        else:
            assert result.returncode != 0 and 'Custom document contract changed: Gen.targets' in result.stdout, result.stdout
    sync('sync', True)
    original = (root / 'mapping.json').read_bytes()
    try:
        mapping['projectDefaults']['documents']['Gen.targets']['sha256'] = '0' * 64
        (root / 'mapping.json').write_text(json.dumps(mapping))
        sync('rejected-document', False)
    finally:
        (root / 'mapping.json').write_bytes(original)
    contract = json.loads((root / 'graph.generated.json').read_text())
    nodes = [n for p in contract['Projects'].values() for n in p.get('Configurations') or [p]]
    inputs = sorted(set(contract['SharedInputs']) | {p for n in nodes for p in n['Inputs']})
    assert len(nodes) == 1
    (root / 'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph","msbuild_graph_runner")\n'
        'msbuild_graph_runner(name="runner")\nmsbuild_graph(name="graph",runner=":runner",contract="graph.generated.json",srcs=' +
        json.dumps(inputs + ['request.txt']) + ',linux_stable_paths=True,linux_worker=True)\n')
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base), 'build', '//:graph', '--jobs=1',
        '--strategy=MSBuildGraph=worker', '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1', '--disk_cache=', '--remote_cache=']
    rows = []
    try:
        for label, generated, hits in [('baseline', 'Generated', 0), ('edit', 'EditedGenerated', 0),
                ('restore', 'Generated', 1)]:
            (root / 'types.txt').write_text(generated)
            (root / 'request.txt').write_text(str(uuid.uuid4()))
            with root.with_name(root.name + '-' + label + '.log').open('w') as log:
                subprocess.run(bazel, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
            artifact = root / 'bazel-bin/graph.graph'
            report = json.loads((artifact / 'report.json').read_text())
            assert (report['hits'], report['misses']) == (hits, 1 - hits), report
            output = artifact / 'workspace'
            assert 'public class ' + generated + ' ' in (output / 'obj/Release/net10.0/Forwarded.cs').read_text()
            digest = hashlib.sha256((output / 'bin/Release/net10.0/Probe.dll').read_bytes()).hexdigest()
            rows.append(dict(case=label, hits=hits, misses=1 - hits, assemblySha256=digest))
        assert rows[0]['assemblySha256'] != rows[1]['assemblySha256'] and rows[0]['assemblySha256'] == rows[2]['assemblySha256']
        root.with_name(root.name + '-summary.json').write_text(json.dumps(dict(rows=rows, changedDocumentRejected=True), indent=2) + '\n')
    finally:
        (root / 'types.txt').write_text('Generated')
    print('PASS: metadata-driven generation, edit, replay restoration and document guard', flush=True)


if __name__ == '__main__':
    main()
