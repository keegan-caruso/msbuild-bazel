"""A cached source-output group must keep relative OriginalItemSpec metadata."""
import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, fixture, run


def metadata_copy(base):
    probe = base / 'metadata-copy'
    probe.mkdir()
    (probe / 'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings></PropertyGroup><ItemGroup>' +
        f'<Compile Include="{ROOT}/tools/GraphBuild/CachedTargetItem.cs" />' +
        ''.join(f'<Reference Include="{name}" HintPath="{SDK}/sdk/10.0.400/{name}.dll" />' for name in
                ['Microsoft.Build', 'Microsoft.Build.Framework', 'Microsoft.Build.Utilities.Core']) + '</ItemGroup></Project>')
    (probe / 'Program.cs').write_text('''using Microsoft.Build.Framework;
using Microsoft.Build.Utilities;
using Microsoft.Build.Execution;
using Microsoft.Build.ProjectCache;
using RulesMSBuild.GraphBuild;
const string original = "relative;a%3B$.cs";
ITaskItem2 source = new CachedTargetItem(Microsoft.Build.Evaluation.ProjectCollection.Escape("/absolute/a;b%3B$.cs"));
source.SetMetadataValueLiteral("OriginalItemSpec", original);
source.SetMetadataValueLiteral("Other", "literal;a%3B$");
var result = CacheResult.IndicateCacheHit(new[] { new PluginTargetResult("Sources", new[] { source }, BuildResultCode.Success) });
var restored = result.BuildResult!["Sources"].Items.Single();
if (restored.ItemSpec != source.ItemSpec || restored.GetMetadata("OriginalItemSpec") != original || restored.GetMetadata("Other") != "literal;a%3B$") throw new Exception("Cache adapter lost literal metadata");
ITaskItem2 destination = new TaskItem("destination");
destination.SetMetadataValueLiteral("OriginalItemSpec", "existing;a%3B$");
source.CopyMetadataTo(destination);
if (destination.GetMetadata("OriginalItemSpec") != "existing;a%3B$") throw new Exception("Overwrote destination metadata");
source.RemoveMetadata("OriginalItemSpec");
var fresh = new TaskItem("fresh");
source.CopyMetadataTo(fresh);
if (fresh.GetMetadata("OriginalItemSpec") != source.ItemSpec) throw new Exception("Lost default source identity");
Console.WriteLine("PASS: cache adapter preserves escaped source identity, destination precedence and ordinary defaults");
''')
    run(DOTNET, 'build', probe / 'Probe.csproj', '-c', 'Release', '-p:UseSharedCompilation=false')
    print(run(DOTNET, probe / 'bin/Release/net10.0/Probe.dll').stdout.strip())


def main():
    with tempfile.TemporaryDirectory(prefix='graph-source-groups-') as temporary:
        base = Path(temporary).resolve()
        metadata_copy(base)
        root = base / 'workspace'
        root.mkdir()
        contract = fixture(root)
        (root / 'Directory.Build.props').write_text('<Project><PropertyGroup><DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences></PropertyGroup></Project>')
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 1; } public enum E { First=40 }')
        project = root / 'P2/P2.csproj'
        project.write_text(project.read_text().replace('</Project>', '<ItemGroup><ProjectReference Include="../P0/P0.csproj" ReferenceOutputAssembly="false" Targets="SourceFilesProjectOutputGroup" OutputItemType="ContractSources" /></ItemGroup><Target Name="UseContractSources" BeforeTargets="CoreCompile" DependsOnTargets="ResolveProjectReferences"><ItemGroup><ContractSources IsRooted="$([System.IO.Path]::IsPathRooted(\'%(ContractSources.OriginalItemSpec)\'))"/><Compile Include="@(ContractSources-&gt;WithMetadataValue(\'Extension\',\'.cs\')-&gt;WithMetadataValue(\'IsRooted\',\'false\'))" /></ItemGroup><WriteLinesToFile File="$(IntermediateOutputPath)source-group-observation.txt" Lines="@(ContractSources-&gt;\'%(Identity)|%(OriginalItemSpec)|%(IsRooted)\')" Overwrite="true"/></Target></Project>'))
        (root / 'P2/Code.cs').write_text('System.Console.WriteLine((int)E.First+P1.Value());')
        manifest, report, cache = base / 'contract.json', base / 'report.json', base / 'cache'
        manifest.write_text(json.dumps(contract))
        def build(hits, value):
            for node in contract['Projects'].values():
                for directory in node['OutputDirectories']:
                    shutil.rmtree(root / directory, ignore_errors=True)
            result = run(DOTNET, RUNNER, 'action', root, manifest, report, cache)
            assert json.loads(report.read_text())['hits'] == hits, report.read_text()
            assert run(DOTNET, root / 'P2/bin/Release/net10.0/P2.dll').stdout.strip() == str(value)
            observed = (root / 'P2/obj/Release/net10.0/source-group-observation.txt').read_text()
            assert '/P0/Code.cs|Code.cs|False' in observed, observed
            return {str(p.relative_to(root)): p.read_bytes() for node in contract['Projects'].values()
                    for directory in node['OutputDirectories'] for p in (root / directory).rglob('*')
                    if p.is_file() and p.suffix in ['.dll', '.pdb']}
        original = build(0, 41)
        assert build(3, 41) == original
        (root / 'P1/Code.cs').write_text('public class P1 { public static int Value() => 2; }')
        edited = build(1, 42)
        # Fresh compilation is the byte/metadata control for partial replay.
        cache = base / 'fresh-control'
        assert build(0, 42) == edited
        print('PASS: source group metadata survives cached producer / recompiled consumer and matches fresh output bytes')


if __name__ == '__main__':
    main()
