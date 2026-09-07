"""Ordinary SDK oracle for the pinned Serilog selected-inner input contract."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

REVISION = '49b5339ce85385dc52d4d8e8f2b8308becf23506'
ROOT = Path(__file__).resolve().parents[2]


def probe(source, package_cache, output):
    source, package_cache, output = (Path(p).resolve() for p in (source, package_cache, output))
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != REVISION:
        raise ValueError('expected pinned Serilog checkout ' + REVISION)
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / 'source'
    archive = subprocess.check_output(['git', '-C', str(source), 'archive', REVISION])
    with tarfile.open(fileobj=io.BytesIO(archive)) as package:
        package.extractall(workspace, filter='data')
    packages = output / 'packages'
    shutil.copytree(package_cache, packages)
    sdk = Path(os.environ.get('SPIKE_DOTNET_ROOT', ROOT / '.tools/dotnet')).resolve()
    env = dict(os.environ, DOTNET_CLI_HOME=str(output / 'home'), NUGET_PACKAGES=str(packages),
               MSBUILDDISABLENODEREUSE='1', DOTNET_CLI_TELEMETRY_OPTOUT='1')
    def run(name, args, cwd=workspace):
        result = subprocess.run([str(sdk / 'dotnet'), *map(str, args)], cwd=cwd, env=env,
                                capture_output=True, text=True, timeout=240)
        (output / (name + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(name + ' failed: ' + result.stdout + result.stderr)
        return result.stdout
    project = 'src/Serilog/Serilog.csproj'
    props = ['-p:Configuration=Release', '-p:TargetFramework=net10.0', '-nodeReuse:false', '-nologo']
    run('restore', ['msbuild', project, '-t:Restore', *props])
    properties = 'TargetFramework,TargetFrameworks,SignAssembly,AssemblyOriginatorKeyFile,IsAotCompatible,PolySharpIncludeRuntimeSupportedAttributes,DefineConstants,GenerateDocumentationFile,MSBuildAllProjects'
    items = 'Analyzer,AdditionalFiles,EditorConfigFiles,EmbeddedResource,CompilerVisibleProperty,PackageReference'
    raw = run('build-inventory', ['msbuild', project, '-t:Build', '-graphBuild', '-isolateProjects', *props,
        '-p:EmitCompilerGeneratedFiles=true', '-getProperty:' + properties, '-getItem:' + items])
    inventory = None
    for index, char in enumerate(raw):
        if char != '{': continue
        try: value, _ = json.JSONDecoder().raw_decode(raw[index:])
        except json.JSONDecodeError: continue
        if isinstance(value, dict) and 'Properties' in value and 'Items' in value:
            inventory = value
            break
    if inventory is None: raise AssertionError('MSBuild did not return the resolved item inventory')
    (output / 'inventory.json').write_text(json.dumps(inventory, indent=2))
    generated = {str(p.relative_to(workspace)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (workspace / 'src/Serilog/obj/Release/net10.0/generated').rglob('*.cs')}
    assembly = workspace / 'src/Serilog/bin/Release/net10.0/Serilog.dll'
    inspector = output / 'oracle'
    inspector.mkdir()
    (inspector / 'Oracle.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings></PropertyGroup><ItemGroup><Reference Include="Serilog"><HintPath>' + str(assembly) + '</HintPath></Reference></ItemGroup></Project>')
    (inspector / 'Program.cs').write_text('''using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using Serilog;
using Serilog.Core;
using Serilog.Events;
var assembly = typeof(Log).Assembly;
using var stream = assembly.GetManifestResourceStream("ILLink.Substitutions.xml")!;
var sink = new Sink();
using (var log = new LoggerConfiguration().WriteTo.Sink(sink).CreateLogger()) log.Information("Hello {Name}", "Ada");
Console.WriteLine(JsonSerializer.Serialize(new { token = Convert.ToHexString(assembly.GetName().GetPublicKeyToken()!), resources = assembly.GetManifestResourceNames(), resourceHash = Convert.ToHexString(SHA256.HashData(stream)), logging = sink.Message }));
class Sink : ILogEventSink { public string Message = ""; public void Emit(LogEvent e) => Message = e.RenderMessage(); }
''')
    run('oracle-build', ['build', inspector / 'Oracle.csproj', '-c', 'Release', '--nologo'], inspector)
    observation = json.loads(run('oracle-run', [inspector / 'bin/Release/net10.0/Oracle.dll'], inspector))
    assets = json.loads((workspace / 'src/Serilog/obj/project.assets.json').read_text())
    selected = assets['targets']['net10.0']
    report = dict(revision=REVISION, scope='ordinary-sdk-selected-serilog-library', sdkVersion=run('sdk-version', ['--version']).strip(),
        properties=inventory['Properties'], analyzers=inventory['Items']['Analyzer'],
        additionalFiles=inventory['Items']['AdditionalFiles'], resources=inventory['Items']['EmbeddedResource'],
        editorConfigs=inventory['Items']['EditorConfigFiles'], compilerVisibleProperties=inventory['Items']['CompilerVisibleProperty'],
        packageReferences=inventory['Items']['PackageReference'], selectedPackages=sorted(selected),
        generatedSources=generated, observation=observation,
        assemblySha256=hashlib.sha256(assembly.read_bytes()).hexdigest(),
        sourceDeclarationPreserved=(workspace / project).read_bytes() == subprocess.check_output(['git', '-C', str(source), 'show', REVISION + ':' + project]))
    generated_root = workspace / 'src/Serilog/obj/Release/net10.0/generated'
    shutil.rmtree(generated_root)
    run('generator-option-build', ['msbuild', project, '-t:Rebuild', *props,
        '-p:EmitCompilerGeneratedFiles=true', '-p:PolySharpExcludeGeneratedTypes=System.Runtime.CompilerServices.IsExternalInit'])
    report['generatorExcludeOptionSources'] = sorted(str(p.relative_to(generated_root)) for p in generated_root.rglob('*.cs'))
    report['analyzerHashes'] = {item['Identity']: hashlib.sha256(Path(item['Identity']).read_bytes()).hexdigest() for item in report['analyzers']}
    report['requiredWorkspaceInputHashes'] = {name: hashlib.sha256((workspace / name).read_bytes()).hexdigest()
        for name in ('src/Serilog/Serilog.csproj', 'Directory.Build.props', 'Directory.Version.props', 'assets/Serilog.snk', 'src/Serilog/ILLink.Substitutions.xml')}
    # Upstream signs conditionally on Exists(key): absent input is silently unsigned.
    (workspace / 'assets/Serilog.snk').unlink()
    run('missing-key-build', ['msbuild', project, '-t:Rebuild', *props])
    run('missing-key-oracle-build', ['build', inspector / 'Oracle.csproj', '-c', 'Release', '--nologo'], inspector)
    report['missingKeyObservation'] = json.loads(run('missing-key-oracle', [inspector / 'bin/Release/net10.0/Oracle.dll'], inspector))
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'package-cache', 'output'): parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    probe(args.source, args.package_cache, args.output)
