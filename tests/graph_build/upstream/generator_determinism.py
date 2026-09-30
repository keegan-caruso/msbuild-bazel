"""Isolate Orchard interceptor nondeterminism without modifying the upstream checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qualify import DOTNET, SDK, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    original = args.source.read_text()
    needle = 'var uniqueId = Guid.NewGuid().ToString("N");'
    assert original.count(needle) == 1
    with tempfile.TemporaryDirectory(prefix='generator-determinism-') as temporary:
        root = Path(temporary).resolve()
        analyzer = root / 'Analyzer'
        app = root / 'App'
        analyzer.mkdir()
        app.mkdir()
        (analyzer / 'Analyzer.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings></PropertyGroup><ItemGroup>' + ''.join(
            f'<Reference Include="{name}" HintPath="$(MSBuildBinPath)/Roslyn/bincore/{name}.dll" Private="false" />' for name in ['Microsoft.CodeAnalysis', 'Microsoft.CodeAnalysis.CSharp']) + '</ItemGroup></Project>')
        (app / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><InterceptorsNamespaces>OrchardCore.DisplayManagement.Generated</InterceptorsNamespaces><EmitCompilerGeneratedFiles>true</EmitCompilerGeneratedFiles></PropertyGroup><ItemGroup><ProjectReference Include="../Analyzer/Analyzer.csproj" ReferenceOutputAssembly="false" OutputItemType="Analyzer" /></ItemGroup></Project>')
        (app / 'Program.cs').write_text('''using OrchardCore.DisplayManagement;
System.Console.WriteLine(((Result)Arguments.From(new { Value = 3 })).Values[0]);
namespace OrchardCore.DisplayManagement {
public interface INamedEnumerable<out T> { }
public sealed class Result(object[] values) : INamedEnumerable<object> { public object[] Values => values; }
public static class Arguments {
public static INamedEnumerable<object> From<T>(T value) where T : notnull => throw new System.Exception("Interceptor did not run");
public static INamedEnumerable<object> From(object[] values, string[] names) => new Result(values);
}}
''')
        rows = []
        for mode in ['original', 'deterministic-probe']:
            source = original if mode == 'original' else original.replace(needle,
                'var uniqueId = System.Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(Encoding.UTF8.GetBytes(info.Location.Version + ":" + info.Location.Data))).ToLowerInvariant();')
            (analyzer / 'Generator.cs').write_text(source)
            samples = []
            generated = []
            for sample in range(2):
                for project in [analyzer, app]:
                    for name in ['bin', 'obj']:
                        shutil.rmtree(project / name, ignore_errors=True)
                run(DOTNET, 'build', app / 'App.csproj', '-c', 'Release', '--source', root,
                    '-p:UseSharedCompilation=false', '-p:NuGetAudit=false')
                assert run(DOTNET, app / 'bin/Release/net10.0/App.dll').stdout.strip() == '3'
                text = next((app / 'obj').rglob('ArgumentsFromInterceptors.g.cs')).read_text()
                generated.append(text)
                samples.append({extension: hashlib.sha256((app / f'bin/Release/net10.0/App.{extension}').read_bytes()).hexdigest() for extension in ['dll', 'pdb']})
            if mode == 'original':
                assert generated[0] != generated[1] and samples[0] != samples[1]
                assert re.sub(r'Interceptor_[a-f0-9]{32}', 'Interceptor_ID', generated[0]) == re.sub(r'Interceptor_[a-f0-9]{32}', 'Interceptor_ID', generated[1])
            else:
                assert generated[0] == generated[1] and samples[0] == samples[1]
            rows.append(dict(mode=mode, samples=samples, generatedEqual=generated[0] == generated[1], runtime='3'))
        args.report.write_text(json.dumps(dict(sourceSha256=hashlib.sha256(args.source.read_bytes()).hexdigest(), sdk=str(SDK.name), runs=rows), indent=2)+'\n')
        print('PASS: raw builds reproduce random interceptor differences; isolated deterministic probe has exact DLL/PDB parity and executes interceptors')


if __name__ == '__main__':
    main()
