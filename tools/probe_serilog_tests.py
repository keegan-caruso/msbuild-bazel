#!/usr/bin/env python3
"""Unchanged upstream Serilog approval test ordinary/native acceptance."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET

from prepare_graph import DOTNET_ROOT

REVISION = '49b5339ce85385dc52d4d8e8f2b8308becf23506'
PROJECT = 'test/Serilog.ApprovalTests/Serilog.ApprovalTests.csproj'
ASSEMBLY = 'test/Serilog.ApprovalTests/bin/Release/net10.0/Serilog.ApprovalTests.dll'
APPROVED = 'test/Serilog.ApprovalTests/Serilog.approved.txt'
FACT = 'ApiApprovalTests.PublicApi_Should_Not_Change_Unintentionally'


def parse_results(path):
    root = ET.parse(path).getroot()
    ns = {'t': 'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    counters = root.find('t:ResultSummary/t:Counters', ns)
    results = root.findall('t:Results/t:UnitTestResult', ns)
    if counters is None or int(counters.attrib['total']) != 1 or int(counters.attrib['executed']) != 1:
        raise AssertionError('exactly one real approval Fact must execute')
    if int(counters.attrib.get('notExecuted', '0')) != 0:
        raise AssertionError('approval Fact was skipped')
    if len(results) != 1 or results[0].attrib['testName'] != FACT:
        raise AssertionError('wrong test selected: ' + str([r.attrib for r in results]))
    return dict(total=1, executed=1, passed=int(counters.attrib['passed']),
                failed=int(counters.attrib['failed']), test=results[0].attrib['testName'],
                outcome=results[0].attrib['outcome'])


def ordinary_probe(source, packages, output):
    source, packages, output = map(lambda p: Path(p).resolve(), (source, packages, output))
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != REVISION:
        raise ValueError('wrong Serilog revision')
    archive = subprocess.check_output(['git', '-C', str(source), 'archive', REVISION])
    output.mkdir(parents=True, exist_ok=False)
    work = output / 'ordinary-source'
    with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
        contents.extractall(work, filter='data')
    # Acquire the already restored closure without touching the upstream checkout.
    shutil.copytree(packages, work / '.nuget/packages')
    env = dict(os.environ, DOTNET_ROOT=str(DOTNET_ROOT), NUGET_PACKAGES=str(work / '.nuget/packages'),
               DOTNET_CLI_HOME=str(output / 'home'), MSBUILDDISABLENODEREUSE='1',
               DiffEngine_Disabled='true', CI='true')
    commands = []

    def run(label, args, expected=0, cwd=work):
        command = list(map(str, [DOTNET_ROOT / 'dotnet', *args]))
        result = subprocess.run(command, cwd=cwd, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
        (output / (label + '.log')).write_text(result.stdout)
        commands.append(dict(label=label, command=command, returncode=result.returncode))
        if (expected == 0 and result.returncode != 0) or (expected != 0 and result.returncode == 0):
            raise AssertionError(label + ': unexpected exit ' + str(result.returncode) + '\n' + result.stdout[-5000:])
        return result

    properties = ['-p:Configuration=Release', '-p:TargetFramework=net10.0', '-nodeReuse:false', '-nologo']
    run('restore', ['msbuild', PROJECT, '-t:Restore', *properties])
    run('build', ['msbuild', PROJECT, '-t:Build', *properties, '-bl:' + str(output / 'ordinary.binlog')])
    assembly = work / ASSEMBLY
    assembly_hash = hashlib.sha256(assembly.read_bytes()).hexdigest()
    cases = {}

    def test(label, expected=0):
        results = output / label
        results.mkdir()
        run(label, ['vstest', assembly, '--logger:trx;LogFileName=results.trx', '--ResultsDirectory:' + str(results)], expected)
        result = parse_results(results / 'results.trx')
        if result['passed'] != (1 if expected == 0 else 0) or result['failed'] != (0 if expected == 0 else 1):
            raise AssertionError('unexpected approval test outcome')
        if hashlib.sha256(assembly.read_bytes()).hexdigest() != assembly_hash:
            raise AssertionError('test command changed the build output')
        result["assemblySha256"] = assembly_hash
        cases[label] = result

    test('ordinary-pass')
    approved = work / APPROVED
    original = approved.read_bytes()
    approved.write_bytes(original + b'\nintentional approval mismatch\n')
    test('ordinary-mismatch', 1)
    approved.unlink()
    test('ordinary-missing-approved', 1)
    approved.write_bytes(original)
    test_source = work / 'test/Serilog.ApprovalTests/ApiApprovalTests.cs'
    original_source = test_source.read_text()
    test_source.write_text(original_source.replace('        var assembly =',
        '        if (DateTime.UtcNow.Year > 0) throw new InvalidOperationException("intentional-test-exception");\n        var assembly ='))
    run('exception-build', ['msbuild', PROJECT, '-t:Build', *properties])
    assembly_hash = hashlib.sha256(assembly.read_bytes()).hexdigest()
    test('ordinary-exception', 1)
    if 'intentional-test-exception' not in (output / 'ordinary-exception.log').read_text():
        raise AssertionError('actual test exception diagnostic missing')
    report = dict(schemaVersion=1, revision=REVISION, sourceArchiveSha256=hashlib.sha256(archive).hexdigest(),
                  scope='unchanged-upstream-approval-test-ordinary', cases=cases,
                  finalExceptionAssemblySha256=assembly_hash, commands=commands, accepted=True)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'packages', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    print(json.dumps(ordinary_probe(args.source, args.packages, args.output), indent=2))


if __name__ == '__main__':
    main()
