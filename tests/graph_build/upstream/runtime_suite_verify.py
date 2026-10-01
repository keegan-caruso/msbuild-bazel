"""Compare graph/raw upstream Pipelines cases and source-runtime producer hashes."""
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

from runtime_full_source import capture_compiled_products, validate_raw_contract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('raw_results', type=Path, help='successful runtime_full_source.py result')
    parser.add_argument('results', type=Path, help='new private evidence directory')
    parser.add_argument('--sdk-absent', action='store_true', help='also run VSTest with only declared host, tests and system libraries mounted')
    args = parser.parse_args()
    root, raw_results, results = args.workspace.resolve(), args.raw_results.resolve(), args.results.resolve()
    contract = json.loads((root / 'graph.generated.json').read_text())
    variants = [v for p in contract['Projects'].values() for v in p.get('Configurations') or [p]]
    assert (raw_results / 'binplace.json').is_file(), 'Successful raw Build and ownership inventory required'
    validate_raw_contract(contract, raw_results)
    graph_products = capture_compiled_products(root / 'bazel-bin/graph.graph/workspace', contract)
    raw_products = capture_compiled_products(raw_results / 'raw-workspace', contract)
    assert graph_products and graph_products.keys() == raw_products.keys()
    assert all(graph_products[name]['sha256'] == raw_products[name]['sha256'] for name in graph_products), 'Raw compiled products differ'
    parity = dict(comparedDllPdbResourceFiles=len(graph_products), configuredNodes=len(variants),
        compilationNodes=sum(bool(v['OutputDirectories'] or v.get('OutputFiles')) for v in variants))
    results.mkdir(parents=True, exist_ok=False)
    suite = json.loads((root / 'suite.json').read_text())
    manifest = json.loads((root / 'application.json').read_text())
    source_host = (root / 'bazel-bin' / suite['host']).resolve(strict=True)
    host = results / 'host'
    shutil.copytree(source_host, host)
    shared = 'shared/Microsoft.NETCore.App/' + manifest['framework']
    expected = {}
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest().upper()
    for name, producer in manifest['managed'].items():
        product = raw_results / 'raw-workspace' / producer['path']
        target = host / shared / name
        assert sha(product) == sha(target), name
        target.chmod(0o644)
        shutil.copyfile(product, target)
        expected[name] = sha(product)
    for name, producer in manifest['native'].items():
        product = root / 'bazel-bin' / producer['producer'] / 'runtime.generated' / name
        assert sha(product) == sha(host / producer['path']), name
        expected[name] = sha(product)
    runner = results / 'runner'
    with zipfile.ZipFile(root / 'suite-runner/vstest.nupkg') as archive:
        archive.extractall(runner)
    directory = raw_results / 'raw-workspace' / suite['directory']
    command = [str(host / 'host.sh'), str(runner / 'contentFiles/any/net9.0/vstest.console.dll'),
        str(directory / suite['assembly']), '/Settings:' + str(directory / '.runsettings'),
        '/Logger:trx;LogFileName=results.trx', '/ResultsDirectory:' + str(results / 'trx'),
        '--', 'RunConfiguration.DotNetHostPath=' + str(host / 'host.sh')]
    start = time.monotonic()
    with (results / 'raw-tests.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=directory,
            env=dict(os.environ, TEST_UNDECLARED_OUTPUTS_DIR=str(results / 'proof')), timeout=900, check=True)
    seconds = time.monotonic() - start
    ns = {'t': 'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    control = Counter((r.get('testName'), r.get('outcome')) for r in
        ET.parse(results / 'trx/results.trx').getroot().findall('.//t:UnitTestResult', ns))
    logs = root / 'bazel-testlogs/pipelines_suite'
    cases = Counter((r.get('name'), 'Failed' if r.find('failure') is not None or r.find('error') is not None
        else 'NotExecuted' if r.find('skipped') is not None else 'Passed') for r in
        ET.parse(logs / 'test.xml').getroot().findall('.//testcase'))
    assert cases and cases == control and not any(o == 'Failed' for _, o in cases), (cases - control, control - cases)
    def proofs(folder):
        rows = [json.loads(path.read_text()) for path in folder.glob('runtime-*.json')]
        if (folder / 'outputs.zip').exists():
            with zipfile.ZipFile(folder / 'outputs.zip') as archive:
                rows += [json.loads(archive.read(name)) for name in archive.namelist()
                         if name.startswith('runtime-') and name.endswith('.json')]
        return rows
    sdk_proofs = []
    if args.sdk_absent:
        namespace = ['bwrap', '--die-with-parent', '--unshare-all', '--new-session', '--cap-drop', 'ALL',
                     '--clearenv', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']
        for path in ['/usr', '/bin', '/lib', '/lib64', '/etc/ld.so.cache', '/etc/os-release', '/etc/passwd', '/etc/group']:
            if Path(path).exists():
                namespace += ['--ro-bind', path, path]
        if Path('/usr/share/dotnet').exists():
            namespace += ['--tmpfs', '/usr/share/dotnet']
        namespace += ['--ro-bind', str(host), '/host', '--ro-bind', str(directory), '/suite',
                      '--ro-bind', str(runner), '/runner', '--bind', str(results), '/results', '--chdir', '/suite',
                      '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'HOME', '/tmp',
                      '--setenv', 'LANG', 'C.UTF-8', '--setenv', 'DOTNET_CLI_HOME', '/tmp',
                      '--setenv', 'TEST_UNDECLARED_OUTPUTS_DIR', '/results/sdk-absent-proof']
        control_command = ['/host/host.sh', '/runner/contentFiles/any/net9.0/vstest.console.dll',
            '/suite/' + suite['assembly'], '/Settings:/suite/.runsettings', '/Logger:trx;LogFileName=results.trx',
            '/ResultsDirectory:/results/sdk-absent-trx', '--', 'RunConfiguration.DotNetHostPath=/host/host.sh']
        with (results / 'sdk-absent.log').open('w') as log:
            subprocess.run(namespace + ['--', '/bin/sh', '-c',
                'test ! -e /qualification/sdk && test ! -e /__rules_msbuild_graph/sdk && exec "$@"',
                'sdk-absent-control', *control_command], stdout=log, stderr=subprocess.STDOUT, timeout=900, check=True)
        absent_cases = Counter((r.get('testName'), r.get('outcome')) for r in
            ET.parse(results / 'sdk-absent-trx/results.trx').getroot().findall('.//t:UnitTestResult', ns))
        assert absent_cases == control, 'SDK-absent suite outcomes differ'
        sdk_proofs = proofs(results / 'sdk-absent-proof')
    observed = {}
    graph_proofs, raw_proofs = proofs(logs / 'test.outputs'), proofs(results / 'proof')
    entries = Counter(p['entry'] for p in graph_proofs)
    assert entries == Counter(p['entry'] for p in raw_proofs) and entries['testhost'], entries
    assert not args.sdk_absent or Counter(p['entry'] for p in sdk_proofs) == entries
    required = {'System.Private.CoreLib.dll', 'libcoreclr.so', 'libclrjit.so', 'dotnet', 'libhostfxr.so', 'libhostpolicy.so'}
    for proof in graph_proofs + raw_proofs + sdk_proofs:
        assert required <= proof['files'].keys(), proof
        for name, row in proof['files'].items():
            assert name in expected and row['sha256'] == expected[name], (name, row)
            observed[name] = row['sha256']
    with (results / 'wrong-corelib.log').open('w') as log:
        rejected = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=directory,
            env=dict(os.environ, TEST_UNDECLARED_OUTPUTS_DIR=str(results / 'wrong-proof'),
                     QUALIFICATION_CORELIB_SHA256='0' * 64), timeout=60)
    assert rejected.returncode != 0 and 'Qualification loaded wrong binary' in (results / 'wrong-corelib.log').read_text()
    report = dict(platform='linux-arm64', cases=sum(cases.values()),
        outcomes=dict(Counter({outcome: sum(count for (_, o), count in cases.items() if o == outcome)
                              for outcome in {o for _, o in cases}})),
        exactNamesAndOutcomesMatch=True, processEntries=dict(entries), observedSourceHashes=observed,
        rawTestSeconds=seconds, sdkAbsent=args.sdk_absent, wrongCorelibExit=rejected.returncode, compiledProducts=parity['comparedDllPdbResourceFiles'],
        scope='selected Pipelines suite on graph-built source framework; native producers shared with raw control, not scored timing')
    (results / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'observedSourceHashes'}), flush=True)


if __name__ == '__main__':
    main()
