"""Compare graph/raw upstream cases and source-runtime producer hashes."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

from runtime_full_source import capture_compiled_products, validate_raw_contract

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests/runtime'))
from case_names import normalize


def proofs(folder):
    values = {p.name: json.loads(p.read_text()) for p in folder.glob('runtime-*.json')}
    if (folder / 'outputs.zip').exists():
        with zipfile.ZipFile(folder / 'outputs.zip') as archive:
            for name in archive.namelist():
                if name.startswith('runtime-') and name.endswith('.json'):
                    value = json.loads(archive.read(name))
                    assert name not in values or values[name] == value, 'Conflicting runtime observation'
                    values[name] = value
    return list(values.values())


def sdk_absent_namespace(host, directory, runner, results):
    command = ['bwrap', '--die-with-parent', '--unshare-all', '--new-session', '--cap-drop', 'ALL',
               '--clearenv', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']
    # The qualified VM executes these tests as UID 0. Upstream identifies root
    # by effective UID and expects it to bypass file permissions. Dropping all
    # capabilities creates an unlike root-without-permissions test environment.
    if os.geteuid() == 0:
        command += ['--cap-add', 'CAP_DAC_OVERRIDE', '--cap-add', 'CAP_DAC_READ_SEARCH']
    # Eight reviewed character-device cases are discovered only when the VM's
    # console exists. Preserve the raw/Bazel device inventory for those cases.
    if Path('/dev/console').exists():
        command += ['--dev-bind', '/dev/console', '/dev/console']
    for path in ['/usr', '/bin', '/lib', '/lib64', '/etc/ld.so.cache', '/etc/os-release', '/etc/passwd', '/etc/group']:
        if Path(path).exists():
            command += ['--ro-bind', path, path]
    if Path('/usr/share/dotnet').exists():
        command += ['--tmpfs', '/usr/share/dotnet']
    return command + ['--ro-bind', str(host), '/host', '--ro-bind', str(directory), '/suite',
        '--ro-bind', str(runner), '/runner', '--bind', str(results), '/results', '--chdir', '/suite',
        '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'HOME', '/tmp', '--setenv', 'LANG', 'C.UTF-8',
        '--setenv', 'DOTNET_CLI_HOME', '/tmp', '--setenv', 'TEST_UNDECLARED_OUTPUTS_DIR', '/results/sdk-absent-proof']


def trx_cases(path):
    ns = {'t': 'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    return Counter((r.get('testName'), r.get('outcome')) for r in
        ET.parse(path).getroot().findall('.//t:UnitTestResult', ns))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('raw_results', type=Path, help='successful runtime_full_source.py result')
    parser.add_argument('results', type=Path, help='new private evidence directory')
    parser.add_argument('--sdk-absent', action='store_true', help='also execute each suite without the build SDK mounted')
    args = parser.parse_args()
    root, raw_results, results = args.workspace.resolve(), args.raw_results.resolve(), args.results.resolve()
    contract = json.loads((root / 'graph.generated.json').read_text())
    assert (raw_results / 'binplace.json').is_file(), 'Successful raw Build and ownership inventory required'
    validate_raw_contract(contract, raw_results)
    graph_products = capture_compiled_products(root / 'bazel-bin/graph.graph/workspace', contract)
    raw_products = capture_compiled_products(raw_results / 'raw-workspace', contract)
    assert graph_products and graph_products.keys() == raw_products.keys()
    assert all(graph_products[n]['sha256'] == raw_products[n]['sha256'] for n in graph_products), 'Raw compiled products differ'
    results.mkdir(parents=True, exist_ok=False)
    suite = json.loads((root / 'suite.json').read_text())
    tests = suite.get('tests') or [suite]
    manifest = json.loads((root / 'application.json').read_text())
    host = results / 'host'
    shutil.copytree((root / 'bazel-bin' / suite['host']).resolve(strict=True), host)
    shared = 'shared/Microsoft.NETCore.App/' + manifest['framework']
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest().upper()
    expected = {}
    for scope, destination in [('managed', shared), ('private', 'private')]:
        for name, producer in manifest.get(scope, {}).items():
            product, target = raw_results / 'raw-workspace' / producer['path'], host / destination / name
            assert sha(product) == sha(target), (scope, name)
            target.chmod(0o644)
            shutil.copyfile(product, target)
            expected.setdefault(name, set()).add(sha(product))
    for name, producer in manifest['native'].items():
        product = root / 'bazel-bin' / producer['producer'] / 'runtime.generated' / name
        assert sha(product) == sha(host / producer['path']), name
        expected.setdefault(name, set()).add(sha(product))
    runner = results / 'runner'
    with zipfile.ZipFile(root / 'suite-runner/vstest.nupkg') as archive:
        archive.extractall(runner)
    required = {'System.Private.CoreLib.dll', 'libcoreclr.so', 'libclrjit.so', 'dotnet', 'libhostfxr.so', 'libhostpolicy.so'}
    rows = []
    wrong_exit = None
    for test in tests:
        label = test['target'].removeprefix('//:')
        evidence = results / label
        evidence.mkdir()
        directory = raw_results / 'raw-workspace' / test['directory']
        settings = directory / '.runsettings'
        if test.get('filter'):
            document = ET.parse(settings)
            configuration = document.getroot().find('RunConfiguration')
            assert configuration is not None
            element = configuration.find('TestCaseFilter')
            if element is None:
                element = ET.SubElement(configuration, 'TestCaseFilter')
            previous = element.text or ''
            element.text = ('(' + previous + ')&' if previous.strip() else '') + '(' + test['filter'] + ')'
            graph_settings = ET.parse(root / 'bazel-bin' / test['settings'])
            assert graph_settings.getroot().findtext('RunConfiguration/TestCaseFilter') == element.text
            settings = evidence / 'raw.runsettings'
            document.write(settings, encoding='utf-8', xml_declaration=True)
        command = [str(host / 'host.sh'), str(runner / 'contentFiles/any/net9.0/vstest.console.dll'),
            str(directory / test['assembly']), '/Settings:' + str(settings), '/Logger:trx;LogFileName=results.trx',
            '/ResultsDirectory:' + str(evidence / 'trx'), '--', 'RunConfiguration.DotNetHostPath=' + str(host / 'host.sh')]
        start = time.monotonic()
        with (evidence / 'raw-tests.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=directory,
                env=dict(os.environ, TEST_UNDECLARED_OUTPUTS_DIR=str(evidence / 'proof')), timeout=1800, check=True)
        seconds = time.monotonic() - start
        control = trx_cases(evidence / 'trx/results.trx')
        logs = root / 'bazel-testlogs' / label
        cases = Counter((r.get('name'), 'Failed' if r.find('failure') is not None or r.find('error') is not None
            else 'NotExecuted' if r.find('skipped') is not None else 'Passed') for r in
            ET.parse(logs / 'test.xml').getroot().findall('.//testcase'))
        assert cases and normalize(cases) == normalize(control) and not any(o == 'Failed' for _, o in cases), (
            label, normalize(cases) - normalize(control), normalize(control) - normalize(cases))
        graph_proofs, raw_proofs = proofs(logs / 'test.outputs'), proofs(evidence / 'proof')
        entries = Counter(p['entry'] for p in graph_proofs)
        assert entries == Counter(p['entry'] for p in raw_proofs) and entries['testhost'], (label, entries)
        absent_proofs = []
        if args.sdk_absent:
            # Mount the independently filtered settings separately when present.
            namespace = sdk_absent_namespace(host, directory, runner, evidence)
            absent_settings = '/suite/.runsettings'
            if test.get('filter'):
                absent_settings = '/results/raw.runsettings'
            absent_command = ['/host/host.sh', '/runner/contentFiles/any/net9.0/vstest.console.dll',
                '/suite/' + test['assembly'], '/Settings:' + absent_settings, '/Logger:trx;LogFileName=results.trx',
                '/ResultsDirectory:/results/sdk-absent-trx', '--', 'RunConfiguration.DotNetHostPath=/host/host.sh']
            with (evidence / 'sdk-absent.log').open('w') as log:
                subprocess.run(namespace + ['--', '/bin/sh', '-c',
                    'test ! -e /qualification/sdk && test ! -e /__rules_msbuild_graph/sdk && exec "$@"',
                    'sdk-absent-control', *absent_command], stdout=log, stderr=subprocess.STDOUT, timeout=1800, check=True)
            assert normalize(trx_cases(evidence / 'sdk-absent-trx/results.trx')) == normalize(control)
            absent_proofs = proofs(evidence / 'sdk-absent-proof')
            assert Counter(p['entry'] for p in absent_proofs) == entries, label
        observed = {}
        for proof in graph_proofs + raw_proofs + absent_proofs:
            assert required <= proof['files'].keys(), (label, proof)
            for name, row in proof['files'].items():
                assert name in expected and row['sha256'] in expected[name], (label, name, row)
                observed.setdefault(name, set()).add(row['sha256'])
        if wrong_exit is None:
            with (evidence / 'wrong-corelib.log').open('w') as log:
                rejected = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=directory,
                    env=dict(os.environ, TEST_UNDECLARED_OUTPUTS_DIR=str(evidence / 'wrong-proof'),
                             QUALIFICATION_CORELIB_SHA256='0' * 64), timeout=60)
            assert rejected.returncode != 0 and 'Qualification loaded wrong binary' in (evidence / 'wrong-corelib.log').read_text()
            wrong_exit = rejected.returncode
        row = dict(assembly=test['assembly'], framework=test.get('framework', 'net10.0'), cases=sum(cases.values()),
            outcomes=dict(Counter({o: sum(n for (_, outcome), n in cases.items() if outcome == o) for _, o in cases})),
            exactNamesAndOutcomesMatch=cases == control, reviewedNamesAndOutcomesMatch=True,
            processEntries=dict(entries), observedSourceHashes={name: sorted(values) for name, values in observed.items()},
            rawTestSeconds=seconds, sdkAbsent=args.sdk_absent)
        rows.append(row)
        report = dict(platform='linux-arm64', tests=rows, compiledProducts=len(graph_products), wrongCorelibExit=wrong_exit,
            scope='selected suites on graph-built source framework; native producers shared with raw control, not scored timing')
        (results / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({key: value for key, value in row.items() if key != 'observedSourceHashes'}), flush=True)


if __name__ == '__main__':
    main()
