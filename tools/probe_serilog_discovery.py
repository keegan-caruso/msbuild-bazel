"""Run RUL-5's identity/eligibility contract against the pinned Serilog library."""
import argparse
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

from discovery_contract import qualify, controlled_environment, SDK
from preparation_identity import IdentityError

REVISION = '49b5339ce85385dc52d4d8e8f2b8308becf23506'


def probe(repository, packages, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source, state = output / 'source', output / 'state'
    source.mkdir()
    archive = subprocess.check_output(['git', '-C', str(repository), 'archive', REVISION])
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(source, filter='data')
    for name in ('polysharp/1.15.0', 'microsoft.net.illink.tasks/10.0.11'):
        shutil.copytree(Path(packages) / name, source / '.nuget/packages' / name)
    env = dict(os.environ, DOTNET_CLI_HOME=str(output / 'home'), NUGET_HTTP_CACHE_PATH=str(output / 'http'))
    restored = subprocess.run([str(SDK / 'dotnet'), 'restore', str(source / 'src/Serilog/Serilog.csproj'),
        '-p:TargetFramework=net10.0', '--packages', str(source / '.nuget/packages')], env=env, cwd=source,
        capture_output=True, text=True, timeout=180)
    (output / 'restore.log').write_text(restored.stdout + restored.stderr)
    assert restored.returncode == 0, restored.stdout + restored.stderr
    entries = [dict(project='src/Serilog/Serilog.csproj', globalProperties={'Configuration':'Release', 'TargetFramework':'net10.0'})]
    report = dict(accepted=False, reuseEnabled=False, upstreamRevision=REVISION, cases={})

    def record(name, value):
        report['cases'][name] = value
        destination = output / 'cases' / name
        destination.mkdir(parents=True)
        for path in (state / 'output').iterdir():
            if path.is_file() and path.suffix in {'.json', '.log', '.sb'}: shutil.copyfile(path, destination / path.name)
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    try:
        baseline = qualify(source, state, entries)
        record('capture', dict(eligible=True, identity=baseline['identity']['key']))
        graph = json.loads((state / 'output/graph.json').read_text())
        assert len(graph['nodes']) == 1
        assert graph['nodes'][0]['discovery']['signAssembly']
        assert any(i['kind'] == 'analyzer' and 'PolySharp' in i['path'] for i in graph['nodes'][0]['inputs'])
        request = json.loads((state / 'output/GraphExport-request.json').read_text())
        request['output'] = str(output / 'ordinary-graph.json')
        request_path = output / 'ordinary-request.json'
        request_path.write_text(json.dumps(request))
        ordinary = subprocess.run([str(SDK / 'dotnet'), str(state / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll'),
            '--request', str(request_path)], cwd=state / 'workspace', env=controlled_environment(state / 'output'),
            capture_output=True, text=True, timeout=180)
        (output / 'ordinary.log').write_text(ordinary.stdout + ordinary.stderr)
        assert ordinary.returncode == 0, ordinary.stderr
        assert json.loads((output / 'ordinary-graph.json').read_text()) == graph
        record('ordinary-parity', dict(equalGraph=True))
        again = qualify(source, state, entries)
        assert baseline['identity']['key'] == again['identity']['key']
        assert baseline['graphSha256'] == again['graphSha256']
        record('fresh-capture', dict(equalIdentity=True, equalGraph=True))
        for path in source.rglob('*'): os.utime(path, (1800000000, 1800000000))
        checked = qualify(source, state, entries, candidate=baseline)
        assert checked['unchanged'] and not checked['discoveryExecuted']
        record('timestamp-and-revalidation', dict(unchanged=True, discoveryExecuted=False))
        for name, relative in (
                ('source', 'src/Serilog/Log.cs'), ('version-import', 'Directory.Version.props'),
                ('signing-key', 'assets/Serilog.snk'),
                ('resource', 'src/Serilog/ILLink.Substitutions.xml'),
                ('restore', 'src/Serilog/obj/project.assets.json'),
                ('package-target', '.nuget/packages/polysharp/1.15.0/buildTransitive/PolySharp.targets'),
                ('package-assembly', '.nuget/packages/polysharp/1.15.0/analyzers/dotnet/cs/PolySharp.SourceGenerators.dll')):
            path = source / relative
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            checked = qualify(source, state, entries, candidate=baseline)
            assert not checked['unchanged'] and not checked['discoveryExecuted']
            record(name, dict(unchanged=False, discoveryExecuted=False))
            if name in {'package-target', 'package-assembly'}:
                try: qualify(source, state, entries)
                except IdentityError as error:
                    assert 'hash-mismatch: package payload' in str(error), str(error)
                    record(name + '-fresh-rejection', dict(rejected=True, diagnostic=str(error)))
                else: raise AssertionError('modified package passed qualification')
            path.write_bytes(original)
        # A changed but supported version input must admit a fresh identity.
        version = source / 'Directory.Version.props'
        original = version.read_bytes()
        version.write_bytes(original.replace(b'4.4.1', b'4.4.2'))
        changed = qualify(source, state, entries)
        assert changed['identity']['key'] != baseline['identity']['key']
        assert changed['graphSha256'] != baseline['graphSha256']
        record('fresh-version-change', dict(eligible=True, changedIdentity=True, changedGraph=True))
        version.write_bytes(original)
        checked = qualify(source, state, entries, candidate=baseline)
        assert checked['unchanged']
        record('restored-inputs', dict(unchanged=True))
        report['accepted'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Existing Git acquisition containing the pinned upstream commit')
    parser.add_argument('--packages', type=Path, required=True, help='Existing package cache containing the two pinned packages')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    probe(args.source, args.packages, args.output)
