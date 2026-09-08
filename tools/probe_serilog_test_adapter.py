"""Native Bazel acceptance for the unchanged upstream approval test project."""
import hashlib
import io
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import zipfile

from prepare_graph import ROOT, DOTNET_ROOT, prepare
from probe_graph_execution import BAZEL
from probe_graph_cache import cache_environment
from probe_bazel import json_stream
from probe_serilog_tests import REVISION, PROJECT, ASSEMBLY, APPROVED, parse_results


def probe(source, packages, output):
    source, packages, output = map(lambda p: Path(p).resolve(), (source, packages, output))
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != REVISION:
        raise ValueError('wrong Serilog revision')
    archive = subprocess.check_output(['git', '-C', str(source), 'archive', REVISION])
    output.mkdir(parents=True, exist_ok=False)
    report = dict(schemaVersion=1, scope='unchanged-upstream-approval-test-native-macos', revision=REVISION,
                  sourceArchiveSha256=hashlib.sha256(archive).hexdigest(), cases={}, accepted=False)
    strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
    base, disk = output / 'bazel-base', output / 'disk-cache'
    stage = 'initialization'
    data_hashes = {}

    def run(label, command, cwd, expected=0):
        result = subprocess.run(list(map(str, command)), cwd=cwd, env=cache_environment(output, cwd),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600)
        (output / (label + '.log')).write_text(result.stdout)
        if (expected == 0 and result.returncode != 0) or (expected != 0 and result.returncode == 0):
            raise AssertionError(label + ' unexpected exit ' + str(result.returncode) + '\n' + result.stdout[-5000:])
        return result

    def fixture(path, mutation=None):
        with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
            contents.extractall(path, filter='data')
        shutil.copytree(packages, path / '.nuget/packages')
        if mutation == 'testdata':
            approved = path / APPROVED
            approved.write_bytes(approved.read_bytes() + b'\nintentional approval mismatch\n')
        elif mutation == 'exception':
            code = path / 'test/Serilog.ApprovalTests/ApiApprovalTests.cs'
            code.write_text(code.read_text().replace('        var assembly =',
                '        if (DateTime.UtcNow.Year > 0) throw new InvalidOperationException("intentional-test-exception");\n        var assembly ='))

    def publish(path, generated, label, mutation=None):
        fixture(path, mutation)
        run(label + '-restore', [DOTNET_ROOT / 'dotnet', 'msbuild', PROJECT, '-t:Restore',
            '-p:Configuration=Release', '-p:TargetFramework=net10.0', '-nodeReuse:false', '-nologo'], path)
        manifest, request = output / (label + '-manifest.json'), output / (label + '-request.json')
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(path), dotnetRoot=str(DOTNET_ROOT),
            sdkVersion='10.0.400', packageRoot=str(path / '.nuget/packages'), entryPoints=[dict(project=PROJECT,
            globalProperties={'Configuration':'Release','TargetFramework':'net10.0'})], output=str(manifest))))
        run(label + '-export', [DOTNET_ROOT / 'dotnet', ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], path)
        exported = json.loads(manifest.read_text())
        entry = next(node for node in exported['nodes'] if node['project'] == 'workspace/' + PROJECT)
        tests = [dict(node=entry['id'], data=['test/Serilog.ApprovalTests/ApiApprovalTests.cs', APPROVED],
                      expectedTests=['ApiApprovalTests.PublicApi_Should_Not_Change_Unintentionally'])]
        if label == 'cold':
            checks = {}
            for name, relative, remove in [
                ('missing-source', 'test/Serilog.ApprovalTests/ApiApprovalTests.cs', True),
                ('changed-source', 'test/Serilog.ApprovalTests/ApiApprovalTests.cs', False),
                ('missing-package', '.nuget/packages/shouldly/4.2.1/shouldly.4.2.1.nupkg', True),
                ('changed-package', '.nuget/packages/shouldly/4.2.1/shouldly.4.2.1.nupkg', False),
                ('missing-testdata', APPROVED, True),
            ]:
                item = path / relative
                original = item.read_bytes()
                rejected = output / ('rejected-' + name)
                try:
                    if remove: item.unlink()
                    else: item.write_bytes(original + b'\nchanged-input\n')
                    try:
                        prepare(path, manifest, rejected, environment=cache_environment(output,path), tests=tests)
                    except (ValueError, RuntimeError, FileNotFoundError) as error:
                        if rejected.exists(): raise AssertionError('rejected preparation published output')
                        diagnostic = str(error).lower()
                        allowed = ('missing', 'no such file') if remove else ('stale', 'hash')
                        if not any(marker in diagnostic for marker in allowed):
                            raise AssertionError('wrong rejection diagnostic for ' + name + ': ' + str(error))
                        checks[name] = str(error)
                        (output / (name + '.log')).write_text(str(error))
                    else: raise AssertionError('invalid input was accepted: ' + name)
                finally:
                    item.write_bytes(original)
            report['rejections'] = checks
        data_hashes[label] = {relative: hashlib.sha256((path / relative).read_bytes()).hexdigest() for relative in tests[0]['data']}
        graph = prepare(path, manifest, generated, environment=cache_environment(output, path), tests=tests)
        if len(graph['nodes']) != 2 or {n['targetFramework'] for n in graph['nodes']} != {'net10.0'}:
            raise AssertionError('ordinary selected-inner two-project graph required')
        return graph

    def invoke(generated, graph, label, projects, execute_test, expected=0, force=False):
        entry = next(node for node in graph['nodes'] if node['project'] == 'workspace/' + PROJECT)
        target = 'test_' + entry['id']
        execution = output / (label + '-execution.json')
        run(label + '-bazel', [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc', '--output_base=' + str(base),
            '--output_user_root=' + str(output / 'bazel-user'), 'test', '//:' + target,
            '--disk_cache=' + str(disk), '--spawn_strategy=' + strategy, '--strategy=MsbuildProject=' + strategy,
            '--cache_test_results=' + ('no' if force else 'yes'),
            '--jobs=2', '--noshow_progress', '--color=no', '--curses=no', '--test_output=errors',
            '--execution_log_json_file=' + str(execution)], generated, expected)
        actions = list(json_stream(execution))
        builds = [a for a in actions if a.get('mnemonic') == 'MsbuildProject']
        active = [a for a in builds if not a.get('cacheHit', False)]
        actual_projects = []
        evidence = output / 'evidence' / label
        evidence.mkdir(parents=True)
        for node in graph['nodes']:
            diagnostics = generated / ('bazel-bin/node_' + node['id'] + '.diagnostics/action.json')
            if diagnostics.exists():
                shutil.copyfile(diagnostics, evidence / (node['id'] + '.action.json'))
        for action in active:
            if action.get('runner') != strategy:
                raise AssertionError('native build sandbox required')
            identity = action['targetLabel'].split(':node_')[-1]
            matched = next(node for node in graph['nodes'] if node['id'] == identity)
            actual_projects.append(Path(matched['project']).stem)
        if sorted(actual_projects) != sorted(projects):
            raise AssertionError(label + ' compiled project set differs: ' + str(actual_projects))
        tests = [a for a in actions if a.get('mnemonic') == 'TestRunner' and not a.get('cacheHit', False)]
        if len(tests) != (1 if execute_test else 0):
            raise AssertionError(label + ' actual test action count differs: ' + str(len(tests)))
        if tests and tests[0].get('runner') != strategy:
            raise AssertionError('native test sandbox required')
        logs = generated / 'bazel-testlogs' / target
        shutil.copytree(logs, evidence / 'testlogs', symlinks=False)
        for path in (evidence / 'testlogs').rglob('outputs.zip'):
            with zipfile.ZipFile(path) as contents:
                contents.extractall(path.parent / 'unpacked')
        results = list((evidence / 'testlogs').rglob('*.trx'))
        if len(results) != 1:
            raise AssertionError('exactly one retained TRX required: ' + str(results))
        runner_reports = list((evidence / 'testlogs').rglob('report.json'))
        if len(runner_reports) != 1:
            raise AssertionError('exactly one test runner report required')
        runner_report = json.loads(runner_reports[0].read_text())
        if runner_report.get('buildOrRestoreInvoked') is not False:
            raise AssertionError('test runner did not enforce no-build/no-restore')
        command = runner_report['command']
        if len(command) < 3 or Path(command[0]).name != 'dotnet' or Path(command[1]).name != 'vstest.console.dll':
            raise AssertionError('test action must directly invoke SDK VSTest')
        if runner_report['dataHashes'] != data_hashes['cold' if label == 'unchanged' else label]:
            raise AssertionError('test action data hashes differ from declared current files')
        if runner_report['total'] != 1 or runner_report['skipped'] != 0:
            raise AssertionError('test runner report did not execute exactly one Fact')
        if runner_report['successful'] != (1 if expected == 0 else 0) or runner_report['failed'] != (0 if expected == 0 else 1):
            raise AssertionError('test runner counts disagree with expected outcome')
        if bool(runner_report['passed']) != (expected == 0) or (runner_report['exitCode'] == 0) != (expected == 0):
            raise AssertionError('real test failure did not propagate through runner')
        if label in ('testdata', 'exception'):
            test_log = runner_reports[0].parent / 'test.log'
            diagnostic = 'Shouldly.ShouldMatchApprovedException' if label == 'testdata' else 'intentional-test-exception'
            if diagnostic not in test_log.read_text():
                raise AssertionError('wrong actual test failure diagnostic for ' + label)
        summary = parse_results(results[0])
        if summary['passed'] != (1 if expected == 0 else 0):
            raise AssertionError('native actual Fact result differs')
        bundle = generated / ('bazel-bin/node_' + entry['id'] + '.bundle')
        shutil.copytree(bundle, evidence / 'bundle')
        inventory = {p.relative_to(bundle).as_posix():dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
            executable=bool(p.stat().st_mode & 0o111)) for p in bundle.rglob('*') if p.is_file()}
        return dict(result=summary, runnerReport=runner_report, buildActions=[dict(cacheHit=a.get('cacheHit',False),runner=a.get('runner')) for a in builds],
                    executedProjects=actual_projects, testExecuted=bool(tests), bundleFiles=inventory)

    try:
        run('exporter-build', [DOTNET_ROOT / 'dotnet', 'build', ROOT / 'tools/GraphExport', '-c','Release','--nologo','-nodeReuse:false'], ROOT)
        preparation, generated = output / 'preparation', output / 'generated'
        stage = 'cold'
        graph = publish(preparation, generated, 'cold')
        shutil.rmtree(preparation)
        report['cases']['cold'] = invoke(generated, graph, 'cold', ['Serilog','Serilog.ApprovalTests'], True)
        stage = 'unchanged'
        report['cases']['unchanged'] = invoke(generated, graph, 'unchanged', [], False)
        for case, projects in [('testdata', []), ('exception', ['Serilog.ApprovalTests'])]:
            stage = case
            shutil.rmtree(generated)
            graph = publish(preparation, generated, case, case)
            shutil.rmtree(preparation)
            report['cases'][case] = invoke(generated, graph, case, projects, True, expected=1)
        stage = 'relocated'
        for path in (generated, base):
            for child in path.rglob('*'):
                if child.is_dir() and not child.is_symlink(): child.chmod(child.stat().st_mode | 0o700)
            shutil.rmtree(path)
        relocated_source, relocated = output / 'relocated-preparation', output / 'relocated-generated'
        graph = publish(relocated_source, relocated, 'relocated')
        shutil.rmtree(relocated_source)
        absent = all(not p.exists() for p in (preparation, generated, base, relocated_source))
        if not absent: raise AssertionError('producer state survived relocation')
        record = invoke(relocated, graph, 'relocated', [], True, force=True)
        if record['buildActions'] != [dict(cacheHit=True,runner='disk cache hit')] * 2:
            raise AssertionError('both build bundles must recover from disk cache')
        if record['bundleFiles'] != report['cases']['cold']['bundleFiles']:
            raise AssertionError('recovered test bundle differs from cold')
        record['producerStateAbsentBeforeBuild'] = absent
        report['cases']['relocated'] = record
        report['accepted'] = True
    except Exception as error:
        report['failure'] = dict(stage=stage, type=type(error).__name__, message=str(error))
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'packages', 'output'):
        parser.add_argument('--' + name, required=True)
    arguments = parser.parse_args()
    probe(arguments.source, arguments.packages, arguments.output)
