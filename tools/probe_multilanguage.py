#!/usr/bin/env python3
"""Compose the generated .NET graph with pinned upstream Python/TypeScript rules."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from probe_graph_execution import probe as graph_probe, BAZEL, ROOT
from probe_bazel import json_stream


def probe(output):
    output = output.resolve()
    baseline = graph_probe(output)
    workspace = output / 'workspace'
    fixture = ROOT / 'tests/fixtures/multilanguage'
    app = next(identity for identity, project in baseline['nodes'].items() if project == 'src/App/App.csproj')
    for name in ('python_app.py', 'typescript_app.ts', 'polyglot_test.py'):
        shutil.copyfile(fixture / name, workspace / name)
    with (workspace / 'MODULE.bazel').open('a') as stream:
        stream.write((fixture / 'MODULE.fragment').read_text())
    with (workspace / 'BUILD.bazel').open('a') as stream:
        stream.write((fixture / 'BUILD.fragment').read_text().replace('APP_ID', app))
    strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
    cases = {}
    dotnet_source = workspace / 'src/src/App/Program.cs'
    original_dotnet = dotnet_source.read_text()
    def run(name):
        execution = output / (name + '-execution.json')
        command = [str(BAZEL), '--batch', '--nohome_rc', '--noworkspace_rc',
                   '--output_base=' + str(output / 'polyglot-base'),
                   '--output_user_root=' + str(output / 'polyglot-user'), 'test', '//:polyglot_test',
                   '--disk_cache=' + str(output / 'polyglot-cache'), '--jobs=2',
                   '--spawn_strategy=' + strategy, '--strategy=MsbuildProject=' + strategy,
                   '--strategy=TsProject=' + strategy, '--test_output=all',
                   '--execution_log_json_file=' + str(execution), '--noshow_progress']
        if name == 'diskCache':
            command.append('--nocache_test_results')
        result = subprocess.run(command, cwd=workspace, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=600)
        (output / (name + '.log')).write_text(result.stdout)
        if result.returncode:
            raise RuntimeError(name + ' failed; see ' + str(output / (name + '.log')) + '\n' + result.stdout[-6000:])
        records = list(json_stream(execution))
        actions = [dict(target=r.get('targetLabel'), mnemonic=r.get('mnemonic'),
                        runner=r.get('runner'), cacheHit=r.get('cacheHit', False)) for r in records]
        cases[name] = dict(returncode=result.returncode, actions=actions, executionLog=execution.name)
        return actions
    cold = run('polyglotCold')
    assert sum(a['mnemonic'] == 'MsbuildProject' and not a['cacheHit'] for a in cold) == 4, cold
    assert any(a['mnemonic'] == 'TsProject' and a['runner'] == strategy for a in cold), cold
    unchanged = run('polyglotUnchanged')
    assert not any(a['mnemonic'] in ('MsbuildProject', 'TsProject') and not a['cacheHit'] for a in unchanged), unchanged
    # Observable language-local mutations; change the independent test oracle too.
    for case, source, before, after in (
        ('pythonEdit', 'python_app.py', 'python-v1', 'python-v2'),
        ('typescriptEdit', 'typescript_app.ts', 'typescript-v1', 'typescript-v2'),
        ('dotnetEdit', 'src/src/App/Program.cs', 'shared-v1:left|shared-v1:right', 'unused'),
    ):
        if case == 'dotnetEdit':
            path = workspace / source
            original = path.read_text()
            path.write_text(original.replace('Console.WriteLine(', 'Console.WriteLine("dotnet-v2|" + '))
            oracle_before, oracle_after = before, 'dotnet-v2|' + before
        else:
            path = workspace / source
            path.write_text(path.read_text().replace(before, after))
            oracle_before, oracle_after = before, after
        oracle = workspace / 'polyglot_test.py'
        oracle.write_text(oracle.read_text().replace(oracle_before, oracle_after))
        actions = run(case)
        managed = [a for a in actions if a['mnemonic'] == 'MsbuildProject' and not a['cacheHit']]
        assert len(managed) == (1 if case == 'dotnetEdit' else 0), managed
        if case == 'typescriptEdit':
            assert any(a['mnemonic'] == 'TsProject' and not a['cacheHit'] for a in actions), actions
        if case != 'typescriptEdit':
            assert not any(a['mnemonic'] == 'TsProject' and not a['cacheHit'] for a in actions), actions
    # Restore the cold fixture, warm it, then recover with no local outputs.
    dotnet_source.write_text(original_dotnet)
    for filename in ('python_app.py', 'typescript_app.ts', 'polyglot_test.py'):
        shutil.copyfile(fixture / filename, workspace / filename)
    run('recoveryBaseline')
    base = output / 'polyglot-base'
    for directory, _, _ in os.walk(base, followlinks=False):
        path = Path(directory)
        if not path.is_symlink():
            path.chmod(path.stat().st_mode | 0o700)
    shutil.rmtree(base)
    assert not base.exists()
    recovery = run('diskCache')
    assert not any(a['mnemonic'] in ('MsbuildProject', 'TsProject') and not a['cacheHit'] for a in recovery), recovery
    assert sum(a['mnemonic'] == 'MsbuildProject' and a['cacheHit'] for a in recovery) == 4, recovery
    assert any(a['mnemonic'] == 'TestRunner' and not a['cacheHit'] and a['runner'] == strategy for a in recovery), recovery
    cases['diskCache']['outputBaseAbsentBeforeBuild'] = True
    cases['diskCache']['testForcedToExecute'] = True
    report = dict(schemaVersion=1, cases=cases, preparationWorkspaceAbsent=baseline['preparationWorkspaceAbsent'],
                  scope='Local runfiles composition and language-local edits; relocation, Aspire and remote support remain open.')
    (output / 'multilanguage-report.json').write_text(json.dumps(report, indent=2))
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(probe(parser.parse_args().output), indent=2))
