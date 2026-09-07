#!/usr/bin/env python3
"""Pinned upstream Serilog library ordinary/native adapter acceptance."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile

from prepare_graph import ROOT, DOTNET_ROOT, prepare
from probe_graph_execution import BAZEL
from probe_graph_cache import cache_environment
from probe_bazel import json_stream

REVISION = '49b5339ce85385dc52d4d8e8f2b8308becf23506'
PROJECT = 'src/Serilog/Serilog.csproj'
ASSEMBLY = 'src/Serilog/bin/Release/net10.0/Serilog.dll'
REFERENCE = 'src/Serilog/obj/Release/net10.0/ref/Serilog.dll'
POLYSHARP = {
    '1.15.0': dict(archiveSha256='9c7fd43995b85fddc55042da0ed78cbc4116a1f5f8be28b87b9f633aac7d2538',
                   generatorSha256='b796a332689665b9f2f25eaa964786121876fa595a28b2a95d04100548e6c264'),
    '1.16.0': dict(archiveSha256='36b6daa6b98bcca5e618db1cdaa63cbbdea74f0153a62d4ad2deada58bbbc0e0',
                   generatorSha256='1b1faa7d7f8efd1655264d23642192da9590ed57f4091df19b0129f68f07703a'),
}
PROPERTIES = ['-p:Configuration=Release', '-p:TargetFramework=net10.0', '-nodeReuse:false', '-nologo']
ANALYZERS = {'Microsoft.CodeAnalysis.CSharp.NetAnalyzers.dll', 'Microsoft.CodeAnalysis.NetAnalyzers.dll',
    'ILLink.CodeFixProvider.dll', 'ILLink.RoslynAnalyzer.dll', 'PolySharp.SourceGenerators.dll',
    'Microsoft.Interop.ComInterfaceGenerator.dll', 'Microsoft.Interop.JavaScript.JSImportGenerator.dll',
    'Microsoft.Interop.LibraryImportGenerator.dll', 'Microsoft.Interop.SourceGeneration.dll',
    'System.Text.Json.SourceGeneration.dll', 'System.Text.RegularExpressions.Generator.dll'}
ORACLE = '''using System.Reflection;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text.Json;
using Serilog;
using Serilog.Core;
using Serilog.Events;
if (args.Length == 2 && args[0] == "key") { using var rsa = new RSACryptoServiceProvider(2048); File.WriteAllBytes(args[1], rsa.ExportCspBlob(true)); return; }
if (args.Length == 2 && args[0] == "identity") { var name = AssemblyName.GetAssemblyName(args[1]); Console.WriteLine(JsonSerializer.Serialize(new { name = name.Name, version = name.Version!.ToString(), token = Convert.ToHexString(name.GetPublicKeyToken()!) })); return; }
var assembly = typeof(Log).Assembly;
using var resource = assembly.GetManifestResourceStream("ILLink.Substitutions.xml")!;
using var file = File.OpenRead(assembly.Location);
using var pe = new PEReader(file);
var sink = new Sink();
using (var log = new LoggerConfiguration().WriteTo.Sink(sink).CreateLogger()) log.Information("Hello {Name}", "Ada");
Console.WriteLine(JsonSerializer.Serialize(new {
 name = assembly.GetName().Name,
 token = Convert.ToHexString(assembly.GetName().GetPublicKeyToken()!),
 strongNameSigned = (pe.PEHeaders.CorHeader!.Flags & CorFlags.StrongNameSigned) != 0,
 version = assembly.GetName().Version!.ToString(), resources = assembly.GetManifestResourceNames(),
 resourceHash = Convert.ToHexString(SHA256.HashData(resource)), logging = sink.Message,
 nullRendering = new ScalarValue(null).ToString(),
 generatedTypes = new[] { "System.Runtime.CompilerServices.IsExternalInit", "System.Runtime.CompilerServices.RequiresLocationAttribute" }.Where(n => assembly.GetType(n) != null).ToArray()
}));
class Sink : ILogEventSink { public string Message = ""; public void Emit(LogEvent e) => Message = e.RenderMessage(); }
'''
REFERENCE_ORACLE = '''using System.Text.Json;
using Serilog;
using Serilog.Core;
using Serilog.Events;
var sink = new Sink();
using (var log = new LoggerConfiguration().WriteTo.Sink(sink).CreateLogger()) log.Information("Hello {Name}", "Ada");
var name = typeof(Log).Assembly.GetName();
Console.WriteLine(JsonSerializer.Serialize(new { name = name.Name, version = name.Version!.ToString(), token = Convert.ToHexString(name.GetPublicKeyToken()!), logging = sink.Message }));
class Sink : ILogEventSink { public string Message = ""; public void Emit(LogEvent e) => Message = e.RenderMessage(); }
'''


def mutate(workspace, case, key):
    if case == 'source':
        path = workspace / 'src/Serilog/Events/ScalarValue.cs'
        original = path.read_text()
        assert original.count('output.Write("null");') == 1
        path.write_text(original.replace('output.Write("null");', 'output.Write("NULL");'))
    elif case == 'resource':
        path = workspace / 'src/Serilog/ILLink.Substitutions.xml'
        path.write_bytes(path.read_bytes() + b'\n<!-- adapter resource mutation -->\n')
    elif case == 'key': (workspace / 'assets/Serilog.snk').write_bytes(key)
    elif case == 'import':
        path = workspace / 'Directory.Version.props'
        path.write_text(path.read_text().replace('4.4.1', '4.5.1'))
    elif case == 'generatorOption':
        path = workspace / 'Directory.Build.props'
        path.write_text(path.read_text().replace('</Project>', '<PropertyGroup><PolySharpExcludeGeneratedTypes>System.Runtime.CompilerServices.IsExternalInit</PolySharpExcludeGeneratedTypes></PropertyGroup></Project>'))
    elif case == 'generatorVersion':
        path = workspace / PROJECT
        original = path.read_text()
        declaration = 'PackageReference Include="PolySharp" Version="1.15.0"'
        assert original.count(declaration) == 1
        path.write_text(original.replace(declaration, 'PackageReference Include="PolySharp" Version="1.16.0"'))


def probe(source, package_cache, output, cases=('source', 'resource', 'key', 'import', 'generatorOption', 'generatorVersion')):
    source, package_cache, output = map(lambda p: Path(p).resolve(), (source, package_cache, output))
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != REVISION:
        raise ValueError('expected pinned Serilog revision ' + REVISION)
    archive = subprocess.check_output(['git', '-C', str(source), 'archive', REVISION])
    output.mkdir(parents=True, exist_ok=False)
    dotnet = DOTNET_ROOT / 'dotnet'
    stage = 'initialization'
    report = dict(schemaVersion=1, scope='R04-selected-serilog-library-native', revision=REVISION,
        sourceArchiveSha256=hashlib.sha256(archive).hexdigest(), requestedMutations=list(cases), cases={}, accepted=False,
        limitations=['library only; upstream approval/test project unqualified', 'native macOS/Linux host only; no remote cache claim', 'shared-worker correctness runs; timings not performance qualification'])

    def run(label, args, cwd):
        result = subprocess.run(list(map(str, args)), cwd=cwd, env=cache_environment(output, cwd),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
        (output / (label + '.log')).write_text(result.stdout)
        if result.returncode: raise RuntimeError(label + ' failed: ' + result.stdout[-4000:])
        return result.stdout.strip()

    def fixture(path, case=None):
        with tarfile.open(fileobj=io.BytesIO(archive)) as contents: contents.extractall(path, filter='data')
        for package_id in ('polysharp', 'microsoft.net.illink.tasks'):
            shutil.copytree(package_cache / package_id, path / '.nuget/packages' / package_id)
        if case: mutate(path, case, key)
        return hashlib.sha256((path / PROJECT).read_bytes()).hexdigest()

    def restore(path, label):
        run(label + '-restore', [dotnet, 'msbuild', PROJECT, '-t:Restore', *PROPERTIES], path)

    inspector = output / 'oracle'
    def observe(assembly, label):
        runtime = inspector / 'bin/Release/net10.0'
        # Cached bundles are read-only; replace the prior oracle copy, preserving source modes.
        (runtime / 'Serilog.dll').unlink(missing_ok=True)
        shutil.copy2(assembly, runtime / 'Serilog.dll')
        return json.loads(run(label + '-oracle', [dotnet, runtime / 'Oracle.dll'], inspector))

    def identity(assembly, label):
        return json.loads(run(label + '-identity', [dotnet, inspector / 'bin/Release/net10.0/Oracle.dll', 'identity', assembly], inspector))

    def generator(node):
        items = [item for item in node['inputs'] if item['kind'] == 'analyzer' and Path(item['path']).name == 'PolySharp.SourceGenerators.dll']
        if len(items) != 1: raise AssertionError('exactly one PolySharp generator input required')
        item = items[0]
        parts = Path(item['path']).parts
        index = parts.index('polysharp')
        version = parts[index + 1]
        archive_name = 'polysharp.' + version + '.nupkg'
        archives = [entry for entry in node['inputs'] if entry['kind'] == 'package' and
            Path(entry['path']).name == archive_name and '/polysharp/' + version + '/' in entry['path']]
        if len(archives) != 1: raise AssertionError('exactly one PolySharp package archive input required')
        return dict(package='PolySharp', version=version, path=item['path'], generatorSha256=item['sha256'],
            archivePath=archives[0]['path'], archiveSha256=archives[0]['sha256'])

    def expected_generator(version):
        return dict(package='PolySharp', version=version,
            path='workspace/.nuget/packages/polysharp/' + version + '/analyzers/dotnet/cs/PolySharp.SourceGenerators.dll',
            generatorSha256=POLYSHARP[version]['generatorSha256'],
            archivePath='workspace/.nuget/packages/polysharp/' + version + '/polysharp.' + version + '.nupkg',
            archiveSha256=POLYSHARP[version]['archiveSha256'])

    reference_expectation = None
    def consume_reference(bundle, label):
        reference = bundle / 'artifacts' / REFERENCE
        implementation = bundle / 'artifacts' / ASSEMBLY
        if not reference.is_file() or not implementation.is_file(): raise AssertionError('reference/runtime assembly missing')
        reference_identity = identity(reference, label + '-reference')
        if reference_identity != reference_expectation: raise AssertionError('adapter reference identity differs from ordinary reference')
        consumer = output / 'reference-consumers' / label
        consumer.mkdir(parents=True)
        (consumer / 'Consumer.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings></PropertyGroup><ItemGroup><Reference Include="Serilog"><HintPath>' + str(reference) + '</HintPath><Private>true</Private></Reference></ItemGroup></Project>')
        (consumer / 'Program.cs').write_text(REFERENCE_ORACLE)
        run(label + '-reference-build', [dotnet, 'build', consumer / 'Consumer.csproj', '-c', 'Release', '-nodeReuse:false', '--nologo'], consumer)
        runtime = consumer / 'bin/Release/net10.0'
        copied = runtime / 'Serilog.dll'
        if not copied.is_file() or hashlib.sha256(copied.read_bytes()).digest() != hashlib.sha256(reference.read_bytes()).digest():
            raise AssertionError('reference-only compile did not copy the declared reference assembly')
        if copied.read_bytes() == implementation.read_bytes(): raise AssertionError('reference-only compile unexpectedly used implementation assembly')
        copied.unlink()
        shutil.copy2(implementation, copied)
        observation = json.loads(run(label + '-reference-run', [dotnet, runtime / 'Consumer.dll'], consumer))
        runtime_identity = {name: observation[name] for name in ('name', 'version', 'token')}
        if runtime_identity != reference_identity or observation['logging'] != 'Hello "Ada"':
            raise AssertionError('reference-compiled consumer runtime identity/behavior mismatch')
        return dict(referenceIdentity=reference_identity, runtimeIdentity=runtime_identity,
            referenceSha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
            implementationSha256=hashlib.sha256(implementation.read_bytes()).hexdigest(),
            logging=observation['logging'], evidence=consumer.relative_to(output).as_posix())

    def ordinary(path, label):
        restore(path, label)
        run(label + '-build', [dotnet, 'msbuild', PROJECT, '-t:Build', '-graphBuild', '-isolateProjects', *PROPERTIES,
            '-bl:' + str(output / (label + '.binlog'))], path)
        return path / ASSEMBLY

    def publish(path, destination, label):
        restore(path, label)
        request, manifest = output / (label + '-request.json'), output / (label + '-manifest.json')
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(path), dotnetRoot=str(DOTNET_ROOT),
            sdkVersion='10.0.100', packageRoot=str(path / '.nuget/packages'),
            entryPoints=[dict(project=PROJECT, globalProperties={'Configuration':'Release','TargetFramework':'net10.0'})], output=str(manifest))))
        run(label + '-export', [dotnet, ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], path)
        if label == 'generatorVersion':
            checks = {}
            for name, relative in (
                ('missing-generator', '.nuget/packages/polysharp/1.16.0/analyzers/dotnet/cs/PolySharp.SourceGenerators.dll'),
                ('missing-package', '.nuget/packages/polysharp/1.16.0/polysharp.1.16.0.nupkg'),
            ):
                item = path / relative
                original = item.read_bytes()
                item.unlink()
                rejected = output / ('rejected-' + name)
                try:
                    try: prepare(path, manifest, rejected, environment=cache_environment(output, path))
                    except (ValueError, RuntimeError, FileNotFoundError) as error:
                        if rejected.exists(): raise AssertionError('rejected generator-version input published a plan')
                        if not str(error).startswith('missing-input:') or 'workspace/' + relative not in str(error):
                            raise AssertionError('wrong generator-version rejection diagnostic: ' + str(error))
                        checks[name] = str(error)
                        (output / (name + '.log')).write_text(str(error))
                    else: raise AssertionError('missing generator-version input accepted: ' + name)
                finally: item.write_bytes(original)
            report['generatorVersionRejections'] = checks
        graph = prepare(path, manifest, destination, environment=cache_environment(output, path))
        if len(graph['nodes']) != 1 or graph['nodes'][0]['project'] != 'workspace/' + PROJECT:
            raise AssertionError('unexpected selected library graph')
        node = graph['nodes'][0]
        if node['globalProperties'] != {'configuration': 'Release', 'targetframework': 'net10.0'}:
            raise AssertionError('selected inner identity changed')
        if not {'workspace/Directory.Build.props', 'workspace/Directory.Version.props'}.issubset({item['path'] for item in node['inputs'] if item['kind'] == 'import'}):
            raise AssertionError('evaluated shared/nested imports missing')
        if node.get('discovery') != dict(signAssembly=True, publicSign=False, delaySign=False):
            raise AssertionError('signing discovery differs from pinned signed pilot')
        if {Path(item['path']).name for item in node['inputs'] if item['kind'] == 'analyzer'} != ANALYZERS:
            raise AssertionError('resolved analyzer closure differs from ordinary inventory')
        signing = [item for item in node['inputs'] if item['kind'] == 'signing']
        if len(signing) != 1 or signing[0]['path'] != 'workspace/assets/Serilog.snk' or signing[0]['sha256'] != hashlib.sha256((path / 'assets/Serilog.snk').read_bytes()).hexdigest():
            raise AssertionError('signing key input missing or wrong')
        resources = [item for item in node['inputs'] if item['kind'] == 'resource']
        if len(resources) != 1 or resources[0].get('metadata', {}).get('LogicalName') != 'ILLink.Substitutions.xml':
            raise AssertionError('resource logical metadata missing')
        return graph

    base, cache = output / 'bazel-base', output / 'disk-cache'
    strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
    def build(workspace, graph, label, executed):
        node = graph['nodes'][0]
        execution = output / (label + '-execution.json')
        run(label + '-bazel', [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc', '--output_base=' + str(base),
            '--output_user_root=' + str(output / 'bazel-user'), 'build', '//:all', '//:node_' + node['id'],
            '--disk_cache=' + str(cache), '--spawn_strategy=' + strategy, '--strategy=MsbuildProject=' + strategy,
            '--jobs=2', '--noshow_progress', '--color=no', '--curses=no', '--execution_log_json_file=' + str(execution)], workspace)
        actions = [r for r in json_stream(execution) if r.get('mnemonic') == 'MsbuildProject']
        active = [r for r in actions if not r.get('cacheHit', False)]
        if len(active) != executed: raise AssertionError('unexpected action count ' + label)
        evidence = output / 'evidence' / label
        evidence.mkdir(parents=True)
        if active:
            if active[0].get('runner') != strategy: raise AssertionError('native sandbox required')
            diagnostics = workspace / f'bazel-bin/node_{node["id"]}.diagnostics'
            shutil.copytree(diagnostics, evidence / 'diagnostics')
            detail = json.loads((diagnostics / 'action.json').read_text())
            if detail['compiledProjects'] != ['Serilog'] or detail['replayHits'] != []: raise AssertionError('unexpected compilation/replay')
        bundle = workspace / f'bazel-bin/node_{node["id"]}.bundle'
        shutil.copytree(bundle, evidence / 'bundle')
        inventory = {p.relative_to(bundle).as_posix():dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(), executable=bool(p.stat().st_mode & 0o111)) for p in bundle.rglob('*') if p.is_file()}
        if not (bundle / 'artifacts/src/Serilog/bin/Release/net10.0/Serilog.xml').is_file(): raise AssertionError('XML documentation missing')
        observation = observe(bundle / 'artifacts' / ASSEMBLY, label)
        record = dict(actions=[dict(cacheHit=r.get('cacheHit', False), runner=r.get('runner')) for r in actions],
            observation=observation, bundleFiles=inventory, evidence=evidence.relative_to(output).as_posix(),
            graph=node, generator=generator(node), executionLog=execution.name)
        if label in ('cold', 'relocated'): record['referenceConsumer'] = consume_reference(bundle, label)
        return record

    try:
        stage = 'ordinary baseline'
        baseline = output / 'ordinary-baseline'
        original_hash = fixture(baseline)
        assembly = ordinary(baseline, 'ordinary-baseline')
        inspector.mkdir()
        (inspector / 'Oracle.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings></PropertyGroup><ItemGroup><Reference Include="Serilog"><HintPath>' + str(assembly) + '</HintPath></Reference></ItemGroup></Project>')
        (inspector / 'Program.cs').write_text(ORACLE)
        run('oracle-build', [dotnet, 'build', inspector / 'Oracle.csproj', '-c', 'Release', '--nologo'], inspector)
        expected = observe(assembly, 'ordinary-baseline')
        if expected['token'] != '24C2F752A8E58A10' or not expected['strongNameSigned'] or expected['logging'] != 'Hello "Ada"': raise AssertionError('ordinary baseline contract differs')
        if expected['resources'] != ['ILLink.Substitutions.xml'] or expected['version'] != '4.4.0.0': raise AssertionError('ordinary resource/version contract differs')
        if expected['resourceHash'] != hashlib.sha256((baseline / 'src/Serilog/ILLink.Substitutions.xml').read_bytes()).hexdigest().upper(): raise AssertionError('resource bytes differ from pinned XML')
        if expected['generatedTypes'] != ['System.Runtime.CompilerServices.IsExternalInit', 'System.Runtime.CompilerServices.RequiresLocationAttribute']: raise AssertionError('ordinary generator type evidence missing')
        report['baselineObservation'] = expected
        ordinary_reference = baseline / REFERENCE
        reference_expectation = identity(ordinary_reference, 'ordinary-reference')
        if reference_expectation != {name: expected[name] for name in ('name', 'version', 'token')}:
            raise AssertionError('ordinary reference/runtime identities differ')
        report['baselineReferenceIdentity'] = reference_expectation
        report['sourceDeclarationSha256'] = original_hash
        key_path = output / 'mutation.snk'
        run('generate-key', [dotnet, inspector / 'bin/Release/net10.0/Oracle.dll', 'key', key_path], inspector)
        key = key_path.read_bytes()
        stage = 'adapter baseline export/preparation'
        run('exporter-build', [dotnet, 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '-nodeReuse:false', '--nologo'], ROOT)
        preparation, generated = output / 'preparation', output / 'generated'
        if fixture(preparation) != original_hash: raise AssertionError('source declaration changed')
        graph = publish(preparation, generated, 'cold')
        shutil.rmtree(preparation)
        stage = 'adapter cold/unchanged'
        cold = build(generated, graph, 'cold', 1)
        if cold['observation'] != expected: raise AssertionError('cold ordinary parity failed')
        if cold['generator'] != expected_generator('1.15.0'): raise AssertionError('baseline generator/package identity differs')
        cold['preparationWorkspaceAbsent'] = not preparation.exists()
        report['cases']['cold'] = cold
        unchanged = build(generated, graph, 'unchanged', 0)
        if unchanged['observation'] != expected or unchanged['bundleFiles'] != cold['bundleFiles']: raise AssertionError('unchanged parity failed')
        report['cases']['unchanged'] = unchanged
        for case in cases:
            stage = 'mutation ' + case
            work = output / ('ordinary-' + case)
            fixture(work, case)
            observation = observe(ordinary(work, 'ordinary-' + case), 'ordinary-' + case)
            if case != 'generatorVersion' and observation == expected: raise AssertionError('mutation has no observable effect: ' + case)
            fixture(preparation, case)
            shutil.rmtree(generated)
            graph = publish(preparation, generated, case)
            shutil.rmtree(preparation)
            record = build(generated, graph, case, 1)
            if record['observation'] != observation: raise AssertionError('mutation ordinary parity failed: ' + case)
            if case == 'generatorVersion':
                if record['generator'] != expected_generator('1.16.0'):
                    raise AssertionError('generator version/payload identity differs')
                if record['generator']['generatorSha256'] == cold['generator']['generatorSha256'] or record['generator']['archiveSha256'] == cold['generator']['archiveSha256']:
                    raise AssertionError('generator version did not change generator payload')
            record['ordinaryObservation'] = observation
            record['preparationWorkspaceAbsent'] = not preparation.exists()
            report['cases'][case] = record
        stage = 'producer-free relocated recovery'
        for directory in (base, generated):
            for p in directory.rglob('*'):
                if p.is_dir() and not p.is_symlink(): p.chmod(p.stat().st_mode | 0o700)
            shutil.rmtree(directory)
        relocated_source, relocated = output / 'relocated-preparation', output / 'relocated-generated'
        fixture(relocated_source)
        graph = publish(relocated_source, relocated, 'relocated')
        shutil.rmtree(relocated_source)
        absent = not base.exists() and not preparation.exists() and not generated.exists() and not relocated_source.exists()
        recovered = build(relocated, graph, 'relocated', 0)
        if recovered['actions'] != [dict(cacheHit=True, runner='disk cache hit')]: raise AssertionError('relocation did not recover from disk')
        if recovered['observation'] != expected or recovered['bundleFiles'] != cold['bundleFiles']: raise AssertionError('relocation changed results')
        recovered['producerStateAbsentBeforeBuild'] = absent
        if not absent: raise AssertionError('producer state survived relocation')
        report['cases']['relocated'] = recovered
        report['accepted'] = True
    except Exception as error:
        report['failure'] = dict(stage=stage, type=type(error).__name__, message=str(error))
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for option in ('source', 'package-cache', 'output'): parser.add_argument('--' + option, required=True, type=Path)
    parser.add_argument('--cases', nargs='*', choices=('source','resource','key','import','generatorOption','generatorVersion'), default=['source','resource','key','import','generatorOption','generatorVersion'])
    args = parser.parse_args()
    probe(args.source, args.package_cache, args.output, args.cases)
