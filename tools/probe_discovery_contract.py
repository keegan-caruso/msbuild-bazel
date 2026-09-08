"""Qualify full SDK discovery identity and its fail-closed boundary on native macOS."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import shutil
import socket

from discovery_contract import qualify, controlled_environment, SDK
from preparation_identity import IdentityError


def probe(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source, state = output / 'source', output / 'state'
    (source / 'imports').mkdir(parents=True)
    (source / 'sources').mkdir()
    (source / 'Directory.Build.props').write_text('<Project/>')
    (source / 'Directory.Build.targets').write_text('<Project/>')
    (source / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>'
        '<Import Project="imports/*.props"/><Import Project="optional.props" Condition="Exists(\'optional.props\')"/>'
        '<ItemGroup><ProjectReference Include="Shared/Shared.csproj"/></ItemGroup></Project>')
    late = output / 'late.props'
    project = source / 'App.csproj'
    project.write_text(project.read_text().replace('</Project>',
        '<Import Project="' + str(late) + '" Condition="Exists(\'' + str(late) + '\')"/></Project>'))
    (source / 'imports/a.props').write_text('<Project><Import Project="nested.data"/></Project>')
    (source / 'imports/nested.data').write_text('<Project><PropertyGroup><BuildStamp>one</BuildStamp></PropertyGroup></Project>')
    (source / 'sources/Code.cs').write_text('class Code { System.DateTime RuntimeClock => System.DateTime.Now; }')
    (source / 'Shared').mkdir()
    (source / 'Shared/Shared.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
    entries = [dict(project='App.csproj', globalProperties={'Configuration':'Release', 'TargetFramework':'net10.0'})]
    report = dict(accepted=False, reuseEnabled=False, cases={})

    def record(name, action):
        result = action()
        report['cases'][name] = result
        evidence = output / 'cases' / name
        evidence.mkdir(parents=True)
        if (state / 'output').is_dir():
            for path in (state / 'output').iterdir():
                if path.is_file() and path.suffix in {'.log', '.json', '.sb'}:
                    shutil.copyfile(path, evidence / path.name)
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def reject(name, change):
        changed = output / ('reject-' + name)
        shutil.copytree(source, changed)
        # The original restore paths are corrected for this new source first.
        for path in changed.rglob('obj/*'):
            if path.is_file(): path.write_bytes(path.read_bytes().replace(str(source).encode(), str(changed).encode()))
        change(changed)
        try:
            qualify(changed, state, entries)
        except IdentityError as error:
            expected = {'external': 'The imported project "' + str(output / 'external.props') + '" was not found.', 'symlink': 'symlinks are not qualified',
                        'sdk-import': 'unqualified SDK/host import'}.get(name, 'unsupported discovery XML')
            if name == 'external': assert (output / 'external.props').is_file()
            assert expected in str(error), str(error)
            return dict(rejected=True, diagnostic=str(error))
        raise AssertionError('accepted unsupported input: ' + name)

    try:
        env = dict(os.environ, DOTNET_CLI_HOME=str(output / 'home'), NUGET_HTTP_CACHE_PATH=str(output / 'http'))
        restore = subprocess.run([str(SDK / 'dotnet'), 'restore', str(source / 'App.csproj'), '--packages', str(source / '.nuget/packages')],
                                 cwd=source, env=env, capture_output=True, text=True, timeout=180)
        (output / 'restore.log').write_text(restore.stdout + restore.stderr)
        assert restore.returncode == 0
        baseline = qualify(source, state, entries)
        (output / 'baseline-certificate.json').write_text(json.dumps(baseline, indent=2))
        graph = json.loads((state / 'output/graph.json').read_text())
        assert len(graph['nodes']) == 2
        record('full-export', lambda: dict(eligible=baseline['eligible'], nodes=len(graph['nodes'])))
        external_file = output / 'external-read.txt'
        external_file.write_text('outside the declared namespace')
        sealed_file = state / 'workspace/sources/Code.cs'
        sealed_bytes = sealed_file.read_bytes()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            boundary_request = state / 'output/boundary-request.json'
            boundary_output = state / 'output/boundary.json'
            boundary_request.write_text(json.dumps(dict(externalFile=str(external_file), sealedFile=str(sealed_file),
                port=listener.getsockname()[1], output=str(boundary_output))))
            boundary = subprocess.run(['/usr/bin/sandbox-exec', '-f', str(state / 'output/sandbox.sb'), str(SDK / 'dotnet'),
                str(state / 'tools/EvaluationProbe/bin/Release/net10.0/EvaluationProbe.dll'), '--boundary-check', str(boundary_request)],
                env=controlled_environment(state / 'output'), cwd=state / 'workspace', capture_output=True, text=True, timeout=30)
            (state / 'output/boundary.log').write_text(boundary.stdout + boundary.stderr)
            assert boundary.returncode == 0, boundary.stderr
            controls = json.loads(boundary_output.read_text())
            assert controls == dict(readDenied=True, writeDenied=True, networkDenied=True), controls
            assert sealed_file.read_bytes() == sealed_bytes
        record('native-enforcement', lambda: controls)
        # An ordinary exporter receives the exact same staged inputs and effective
        # request as the restricted process. No source checkout build is implied.
        request = json.loads((state / 'output/GraphExport-request.json').read_text())
        request['output'] = str(output / 'ordinary-graph.json')
        request_path = output / 'ordinary-request.json'
        request_path.write_text(json.dumps(request))
        ordinary = subprocess.run([str(SDK / 'dotnet'), str(state / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll'),
                                   '--request', str(request_path)], cwd=state / 'workspace', env=controlled_environment(state / 'output'), capture_output=True, text=True, timeout=180)
        (output / 'ordinary.log').write_text(ordinary.stdout + ordinary.stderr)
        assert ordinary.returncode == 0, ordinary.stderr
        assert json.loads((output / 'ordinary-graph.json').read_text()) == graph
        record('ordinary-parity', lambda: dict(equal=True))
        second = qualify(source, state, entries)
        assert baseline['identity']['key'] == second['identity']['key']
        assert baseline['graphSha256'] == second['graphSha256']
        record('fresh-capture', lambda: dict(equalIdentity=True, equalGraph=True))

        def revalidate(expected):
            result = qualify(source, state, entries, candidate=baseline)
            assert result['unchanged'] == expected
            assert not result['discoveryExecuted']
            return dict(unchanged=expected, discoveryExecuted=False)

        record('candidate-validation', lambda: revalidate(True))
        late.write_text('<Project/>')
        record('external-absence-invalidated', lambda: revalidate(False))
        try: qualify(source, state, entries)
        except IdentityError as error:
            assert 'sandbox hid an existing undeclared input' in str(error), str(error)
            record('masked-external-input', lambda: dict(rejected=True, diagnostic=str(error)))
        else: raise AssertionError('sandbox silently hid a new external input')
        late.unlink()
        for path in source.rglob('*'): os.utime(path, (1800000000, 1800000000))
        record('timestamp-only', lambda: revalidate(True))
        for name, path, text in (
                ('nested-import', 'imports/nested.data', '<Project><PropertyGroup><BuildStamp>two</BuildStamp></PropertyGroup></Project>'),
                ('optional-import', 'optional.props', '<Project/>'),
                ('wildcard-member', 'imports/new.props', '<Project/>'),
                ('source-membership', 'sources/New.cs', 'class New {}'),
                ('consumer-extra', 'invalidation.txt', 'random-value'),
                ('restore-content', 'obj/project.assets.json', '{}'),
                ('generated-wrapper', 'obj/App.csproj.nuget.g.props', '<Project/>'),
                ('project-reference', 'Shared/Shared.csproj', '<Project/>')):
            target = source / path
            old = target.read_bytes() if target.exists() else None
            target.write_text(text)
            record(name, lambda: revalidate(False))
            if old is None: target.unlink()
            else: target.write_bytes(old)
        record('restored-inputs', lambda: revalidate(True))
        for name, body in (
                ('wall-clock', '<PropertyGroup><Value>$([System.DateTime]::UtcNow)</Value></PropertyGroup>'),
                ('file-read-bypass', '<PropertyGroup><Value>$([System.IO.File]::ReadAllText(\'sources/Code.cs\'))</Value></PropertyGroup>'),
                ('timestamp-metadata', '<PropertyGroup><Value>@(Compile->\'%(ModifiedTime)\')</Value></PropertyGroup>'),
                ('custom-target', '<Target Name="X" BeforeTargets="ProcessFrameworkReferences"/>'),
                ('arbitrary-extension', '<Import Project="custom.data"/>')):
            def change(root, body=body, name=name):
                (root / 'imports/nested.data').write_text('<Project>' + body + '</Project>')
                if name == 'arbitrary-extension':
                    (root / 'imports/custom.data').write_text('<Project><Target Name="X"/></Project>')
            record(name, lambda name=name, change=change: reject(name, change))
        external = output / 'external.props'
        external.write_text('<Project/>')
        record('external-import', lambda: reject('external', lambda root:
            (root / 'imports/nested.data').write_text('<Project><Import Project="' + str(external) + '"/></Project>')))
        record('symlink', lambda: reject('symlink', lambda root: (root / 'link').symlink_to('sources/Code.cs')))
        unqualified_sdk = SDK / 'sdk/10.0.400/Sdks/Microsoft.NET.Sdk.WebAssembly/Sdk/TargetFrameworks.props'
        record('unqualified-sdk-import', lambda: reject('sdk-import', lambda root:
            (root / 'imports/nested.data').write_text('<Project><Import Project="' + str(unqualified_sdk) + '"/></Project>')))
        corrupted = copy.deepcopy(baseline)
        corrupted['graphSha256'] = '0' * 64
        try: qualify(source, state, entries, candidate=corrupted)
        except IdentityError: record('corrupt-certificate', lambda: dict(rejected=True))
        else: raise AssertionError('accepted corrupt certificate')
        other = copy.deepcopy(entries)
        other[0]['globalProperties']['Configuration'] = 'Debug'
        try: qualify(source, state, other, candidate=baseline)
        except IdentityError as error:
            assert 'only Release/net10.0' in str(error)
            record('unqualified-configuration', lambda: dict(rejected=True))
        else: raise AssertionError('accepted unqualified configuration')
        report['accepted'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    probe(parser.parse_args().output)
