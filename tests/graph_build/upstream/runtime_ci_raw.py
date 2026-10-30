"""Measure raw MSBuild and the same app/eight suites used by the runtime CI demo.

Requires a prepared full-source raw workspace and built graph demo assets. Native
runtime files and unchanged demo helpers are shared prerequisites, not cold native
build scores. Package/SDK acquisition and asset preparation precede the timer.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile

from runtime_full_source import capture_compiled_products, replay_omissions
from runtime_recovered_tests import edited_sources, normalize
from runtime_suite_verify import proofs, trx_cases

ROOT = Path(__file__).resolve().parents[3]


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def clean_products(raw, contract):
    raw = raw.resolve()
    nodes = [node for project in contract['Projects'].values() for node in project['Configurations']]
    inputs = set(contract['SharedInputs']) | set(contract.get('DefinitionDigests', {}))
    inputs.update(path for project in contract['Projects'].values() for path in project.get('Inputs', []))
    inputs.update(path for node in nodes for path in node['Inputs'])
    inputs.update(contract['Restore']['Inputs'])
    directories = {path for node in nodes for path in node['OutputDirectories']}
    directory_targets, file_targets = [], []
    for name in sorted(directories):
        path = Path(name)
        assert path.parts and not path.is_absolute() and '..' not in path.parts
        assert path.parts[0] not in ['.nuget', '.package-source', '.qualification']
        assert not any(Path(source).is_relative_to(path) for source in inputs), 'Owned output overlaps authored inputs'
        target = raw / path
        assert target.resolve().is_relative_to(raw) and not target.is_symlink()
        directory_targets.append(target)
    for name in {path for node in nodes for path in node.get('OutputFiles', [])} | set(contract['Restore'].get('Outputs', [])):
        path = Path(name)
        assert path.parts and not path.is_absolute() and '..' not in path.parts and name not in inputs
        assert path.parts[0] not in ['.nuget', '.package-source', '.qualification']
        target = raw / path
        assert target.resolve().is_relative_to(raw)
        assert not target.is_dir()
        file_targets.append(target)
    for target in directory_targets:
        if target.exists():
            shutil.rmtree(target)
    for target in file_targets:
        target.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path, help='built runtime CI graph, with source host and demo helper outputs')
    parser.add_argument('raw_results', type=Path, help='runtime_full_source.py control or --prepare-only workspace')
    parser.add_argument('assets', type=Path, help='owned reusable native/runner/helper template; created if absent')
    parser.add_argument('results', type=Path, help='fresh evidence directory')
    parser.add_argument('--case', choices=['unchanged', 'body', 'api'], default='unchanged')
    parser.add_argument('--edit-token', help='same unique token passed to runtime_recovered_tests.py')
    parser.add_argument('--fresh-outputs', action='store_true', help='fresh CI outputs/Restore assets; retain verified SDK/NuGet packages')
    parser.add_argument('--prepare-only', action='store_true', help='prepare shared native/demo prerequisites without measuring a case')
    parser.add_argument('--host-space-path', type=Path, required=True)
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert (args.case == 'unchanged') == (args.edit_token is None)
    root, raw_results, assets, results = (path.resolve() for path in [args.workspace, args.raw_results, args.assets, args.results])
    raw = raw_results / 'raw-workspace'
    assert raw.is_dir() and (raw / '.qualification/Raw.dll').is_file()
    assert not results.exists() and not results.is_relative_to(raw) and not raw.is_relative_to(results)
    assert not results.is_relative_to(root) and not root.is_relative_to(results)
    assert not assets.is_relative_to(raw) and not assets.is_relative_to(root)
    contract = json.loads((root / 'graph.generated.json').read_text())
    assert json.loads((raw / 'graph.generated.json').read_text()) == contract
    suite = json.loads((root / 'suite.json').read_text())
    application = json.loads((root / 'application.json').read_text())
    assert len(suite['tests']) == 8
    if not assets.exists():
        assets.mkdir(parents=True)
        shutil.copytree((root / 'bazel-bin' / suite['host']).resolve(strict=True), assets / 'host')
        shutil.copytree((root / 'bazel-bin/app_build.graph/workspace/bin/Release/net10.0').resolve(strict=True), assets / 'app')
        with zipfile.ZipFile(root / 'suite-runner/vstest.nupkg') as archive:
            archive.extractall(assets / 'runner')
        manifest = {str(path.relative_to(assets)): digest(path) for path in assets.rglob('*') if path.is_file()}
        (assets / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    # Verify shared prerequisites outside the measured workflow.
    for name, expected in json.loads((assets / 'manifest.json').read_text()).items():
        assert digest(assets / name) == expected, name
    if args.prepare_only:
        print('PASS: native runtime, runner and unchanged demo helpers prepared; no timed case executed')
        return
    results.mkdir(parents=True)
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    environment = dict(os.environ, DOTNET_ROOT=str(sdk), DOTNET_HOST_PATH=str(sdk / 'dotnet'), MSBUILDDISABLENODEREUSE='1')
    for key in ['RULES_MSBUILD_PROJECT_CACHE_URL', 'RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', 'RULES_MSBUILD_GRAPH_PROFILE']:
        environment.pop(key, None)
    scratch = results / 'scratch'
    scratch.mkdir()
    stable = '/__rules_msbuild_graph/output/workspace'
    host_command = ['bash', str(ROOT / 'tests/graph_build/upstream/runtime_raw.sh'), str(sdk), str(raw), str(scratch)]
    build = host_command + [stable + '/.qualification/Raw.dll', stable, stable + '/graph.generated.json', 'build']

    def execute(command, log_name, cwd, env=environment):
        with (results / log_name).open('w') as log:
            subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=3600)

    mutation = json.loads(Path(__file__).with_name('runtime_source_host_edit.json').read_text())
    originals = {mutation[field]: (raw / mutation[field]).read_bytes() for field in ['implementation', 'reference']}
    assert all((root / name).read_bytes() == data for name, data in originals.items())
    if args.fresh_outputs:
        clean_products(raw, contract)
    else:
        execute(build, 'baseline-build.log', raw)
    changes = {} if args.case == 'unchanged' else edited_sources(originals, mutation, args.case, args.edit_token)
    try:
        for name, data in changes.items():
            (raw / name).write_bytes(data)
        subprocess.run(['fstrim', '/'], capture_output=True, check=True)
        disk = os.statvfs(args.host_space_path)
        assert disk.f_bavail * disk.f_frsize >= 12 * 1024**3, 'Insufficient physical host headroom'
        start = time.monotonic()
        if args.fresh_outputs:
            configs = [path for path in raw.iterdir() if path.name.lower() == 'nuget.config']
            config, = configs
            execute(host_command + [stable + '/.qualification/Raw.dll', stable, stable + '/graph.generated.json',
                'restore', config.name], 'restore.log', raw)
        restore_end = time.monotonic()
        execute(build, 'build.log', raw)
        build_end = time.monotonic()
        host = results / 'host'
        shutil.copytree(assets / 'host', host)
        shared = 'shared/Microsoft.NETCore.App/' + application['framework']
        for scope, directory in [('managed', shared), ('private', 'private')]:
            for name, producer in application.get(scope, {}).items():
                source, destination = raw / producer['path'], host / directory / name
                destination.chmod(0o644)
                shutil.copyfile(source, destination)
        publication_end = time.monotonic()
        execute([str(host / 'host.sh'), str(assets / 'app/App.dll')], 'app.log', raw,
            dict(environment, RUNTIME_PROVIDER='source', TEST_UNDECLARED_OUTPUTS_DIR=str(results / 'app-proof')))
        signatures, outcomes = {}, Counter()
        for selection in suite['tests']:
            label = selection['target'].removeprefix('//:')
            evidence = results / label
            evidence.mkdir()
            directory = raw / selection['directory']
            settings = directory / '.runsettings'
            if selection.get('filter'):
                document = ET.parse(settings)
                configuration = document.getroot().find('RunConfiguration')
                assert configuration is not None
                element = configuration.find('TestCaseFilter')
                if element is None:
                    element = ET.SubElement(configuration, 'TestCaseFilter')
                previous = element.text or ''
                element.text = ('(' + previous + ')&' if previous.strip() else '') + '(' + selection['filter'] + ')'
                settings = evidence / 'runsettings.xml'
                document.write(settings, encoding='utf-8', xml_declaration=True)
            execute([str(host / 'host.sh'), str(assets / 'runner/contentFiles/any/net9.0/vstest.console.dll'),
                str(directory / selection['assembly']), '/Settings:' + str(settings), '/Logger:trx;LogFileName=results.trx',
                '/ResultsDirectory:' + str(evidence / 'trx'), '--', 'RunConfiguration.DotNetHostPath=' + str(host / 'host.sh')],
                label + '.log', directory, dict(environment, TEST_UNDECLARED_OUTPUTS_DIR=str(evidence / 'proof')))
        end = time.monotonic()
        # Verification is outside the measured Build/publication/test interval.
        expected_runtime = {}
        for scope in ['managed', 'private']:
            for name, producer in application.get(scope, {}).items():
                expected_runtime.setdefault(name, set()).add(digest(raw / producer['path']).upper())
        for name, producer in application['native'].items():
            expected_runtime.setdefault(name, set()).add(digest(assets / 'host' / producer['path']).upper())
        for selection in suite['tests']:
            evidence = results / selection['target'].removeprefix('//:')
            cases = Counter()
            for (name, outcome), count in trx_cases(evidence / 'trx/results.trx').items():
                cases[name, {'Passed': 'passed', 'NotExecuted': 'skipped', 'Failed': 'failed'}[outcome]] += count
                outcomes[{'Passed': 'passed', 'NotExecuted': 'skipped', 'Failed': 'failed'}[outcome]] += count
            canonical = sorted((name, outcome, count) for (name, outcome), count in normalize(cases).items())
            signatures[selection['target']] = dict(cases=sum(cases.values()), sha256=hashlib.sha256(json.dumps(canonical).encode()).hexdigest())
            observed = proofs(evidence / 'proof')
            assert observed
            for proof in observed:
                assert {'System.Private.CoreLib.dll', 'libcoreclr.so', 'libclrjit.so', 'dotnet', 'libhostfxr.so', 'libhostpolicy.so'} <= proof['files'].keys()
                for name, record in proof['files'].items():
                    assert record['sha256'] in expected_runtime.get(name, set()), (name, record)
        assert outcomes == Counter(passed=118952, skipped=64), outcomes
        assert 'Hello from source-built .NET' in (results / 'app.log').read_text()
        files = capture_compiled_products(raw, contract)
        omitted = replay_omissions(contract)
        files = {name: data for name, data in files.items() if name not in omitted}
        row = dict(case=args.case, freshOutputs=args.fresh_outputs, editToken=args.edit_token,
            contractSha256=digest(root / 'graph.generated.json'),
            sourceEdits={name: hashlib.sha256(data).hexdigest() for name, data in changes.items()},
            restoreSeconds=restore_end - start, buildSeconds=build_end - restore_end,
            publicationSeconds=publication_end - build_end, testSeconds=end - publication_end, commandSeconds=end - start,
            verificationSeconds=time.monotonic() - end, outcomes=dict(outcomes), executedTests=9,
            signatures=signatures, files=files, nativePrerequisites='shared declared source-native binaries',
            scope='raw MSBuild graph and direct VSTest/app; SDK/packages and unchanged native/demo helpers prepared')
        (results / 'summary.json').write_text(json.dumps(row, indent=2) + '\n')
        print(json.dumps({key: value for key, value in row.items() if key not in ['files', 'signatures']}), flush=True)
    finally:
        for name, data in originals.items():
            (raw / name).write_bytes(data)


if __name__ == '__main__':
    main()
