"""Shared evaluation state stays inside a graph pass and refreshes between passes."""
import json
from pathlib import Path
import tempfile

from qualify import DOTNET, ROOT, SDK, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-evaluation-context-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        contract = fixture(root)
        (root / 'Directory.Build.props').write_text('<Project><Import Project="optional.props" Condition="Exists(\'optional.props\')" /><ItemGroup Condition="false"><Compile Include="$([System.Int32]::Parse(\'inactive-item-must-not-expand\'))" /></ItemGroup></Project>')
        manifest = base / 'contract.json'
        manifest.write_text(json.dumps(contract))
        probe = base / 'probe'
        probe.mkdir()
        sources = [p for p in (ROOT / 'tools/GraphBuild').glob('*.cs') if p.name != 'Program.cs']
        (probe / 'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk">'
            f'<Import Project="{ROOT}/tools/MSBuildAdapter.props" /><PropertyGroup>'
            '<TargetFramework>net11.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings>'
            '<Nullable>enable</Nullable></PropertyGroup><ItemGroup>' +
            ''.join(f'<Compile Include="{p}" />' for p in sources) + '</ItemGroup></Project>')
        (probe / 'Program.cs').write_text('''using System.Text.Json;
using RulesMSBuild.GraphBuild;
var root = args[0];
var sdk = args[2];
Directory.SetCurrentDirectory(root);
System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (context, name) =>
    File.Exists(Path.Combine(sdk, "sdk/11.0.100", name.Name + ".dll")) ? context.LoadFromAssemblyPath(Path.Combine(sdk, "sdk/11.0.100", name.Name + ".dll")) : null;
var contract = JsonSerializer.Deserialize<GraphContract>(File.ReadAllText(args[1]))!;
using (var first = new GraphInputs(contract, root, sdk))
{
    if (first.Graph.ProjectNodes.Any(node => node.ProjectInstance.GetPropertyValue("OptionalMarker").Length != 0)) throw new Exception("Unexpected initial import");
    foreach (var node in first.Graph.ProjectNodes) node.ProjectInstance.SetProperty("TargetMutation", "must-not-survive");
}
File.WriteAllText("optional.props", "<Project><PropertyGroup><OptionalMarker>fresh</OptionalMarker></PropertyGroup></Project>");
File.WriteAllText("P0/Extra.cs", "public class Extra { }");
contract = contract with { SharedInputs = [..contract.SharedInputs, "optional.props"] };
contract.Projects["P0/P0.csproj"] = contract.Projects["P0/P0.csproj"] with { Inputs = [..contract.Projects["P0/P0.csproj"].Inputs, "P0/Extra.cs"] };
using (var second = new GraphInputs(contract, root, sdk))
{
    if (second.Graph.ProjectNodes.Any(node => node.ProjectInstance.GetPropertyValue("OptionalMarker") != "fresh" || node.ProjectInstance.GetPropertyValue("TargetMutation").Length != 0)) throw new Exception("Stale project or import state");
    var leaf = second.Graph.ProjectNodes.Single(node => node.ProjectInstance.FullPath.EndsWith("P0.csproj"));
    if (!leaf.ProjectInstance.GetItems("Compile").Any(item => item.EvaluatedInclude == "Extra.cs")) throw new Exception("Stale glob");
}
File.WriteAllText("optional.props", "<Project><PropertyGroup><OptionalMarker>edited</OptionalMarker></PropertyGroup></Project>");
using var third = new GraphInputs(contract, root, sdk);
if (third.Graph.ProjectNodes.Any(node => node.ProjectInstance.GetPropertyValue("OptionalMarker") != "edited")) throw new Exception("Stale import bytes");
File.WriteAllText("Directory.Build.props", File.ReadAllText("Directory.Build.props").Replace("Condition=\\\"false\\\"", "Condition=\\\"true\\\""));
bool rejected = false;
try { using var active = new GraphInputs(contract, root, sdk); }
catch (Exception error) when (error.ToString().Contains("inactive-item-must-not-expand")) { rejected = true; }
if (!rejected) throw new Exception("Active item expression was skipped");
Console.WriteLine("PASS: inactive items skipped; active conditions, new imports, globs, import bytes and project mutations refresh");
''')
        run(DOTNET, 'build', probe / 'Probe.csproj', '-c', 'Release')
        result = run(DOTNET, probe / 'bin/Release/net11.0/Probe.dll', root, manifest, SDK)
        print(result.stdout.strip())


if __name__ == '__main__':
    main()
