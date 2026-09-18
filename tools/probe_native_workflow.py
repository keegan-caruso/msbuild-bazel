"""Pinned real Build/Test controls through the normal native workflow command."""
import argparse
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
from unittest.mock import patch

import native_workflow

from native_workflow import Workflow, bootstrap, DOTNET_ROOT, BAZEL
from probe_serilog_tests import REVISION, PROJECT, APPROVED

TESTS = dict(data=['test/Serilog.ApprovalTests/ApiApprovalTests.cs', APPROVED],
             expectedTests=['ApiApprovalTests.PublicApi_Should_Not_Change_Unintentionally'])


def fixture(checkout, packages, output):
    archive = subprocess.check_output(['git', '-C', str(checkout), 'archive', REVISION])
    with tarfile.open(fileobj=io.BytesIO(archive)) as contents: contents.extractall(output, filter='data')
    shutil.copytree(packages, output / '.nuget/packages')
    env = dict(os.environ, NUGET_PACKAGES=str(output / '.nuget/packages'))
    subprocess.run([str(DOTNET_ROOT / 'dotnet'), 'msbuild', PROJECT, '-t:Restore', '-p:Configuration=Release',
        '-p:TargetFramework=net10.0', '-nodeReuse:false', '-nologo'], cwd=output, env=env, check=True)
    return output


def probe(checkout, packages, output, *, reuse=False, incremental_sources=False):
    output = Path(output).resolve(); output.mkdir(exist_ok=False, parents=True)
    bootstrap()
    source = fixture(checkout, packages, output / 's')
    state = output / 'state'
    workflow = Workflow(source, state, PROJECT, tests=TESTS, reuse=reuse, incremental_sources=incremental_sources)
    cases = []
    def run(label, compiles, failure=False):
        try: workflow.run(output / label, operation='test', force_tests=True)
        except RuntimeError:
            if not failure: raise
        else: assert not failure, 'expected failure'
        result = json.loads((output / label / 'report.json').read_text())
        assert result['accepted'] != failure
        assert result['compiles'] == compiles
        assert result['testActions'] == 1 and result['test']['total'] == 1 and result['test']['skipped'] == 0
        assert result['test']['successful'] == (0 if failure else 1)
        assert not result['test']['buildOrRestoreInvoked']
        if not failure: assert result['test']['runtimeHashes'] == result['runtimeHashes'], 'test consumed stale compile runtime'
        cases.append(dict(label=label, compiles=compiles, testPassed=result['test']['passed']))
        print(label, compiles, result['test']['passed'], flush=True)
        return result
    try:
        cold = run('cold', 2)
        recovered = run('recovered', 0)
        assert cold['runtimeHashes'] == recovered['runtimeHashes']
        if reuse:
            assert not cold['preparation']['reused'] and recovered['preparation']['reused']
            assert not recovered['preparation']['discoveryExecuted']
            assert not recovered['preparation']['materializationExecuted']
        approved = source / APPROVED; original = approved.read_bytes()
        approved.write_bytes(original + b'\nintentional mismatch\n')
        pointer = (state / 'cache.json').read_bytes()
        run('golden-mismatch', 0, True)
        assert (state / 'cache.json').read_bytes() == pointer, 'failed test published cache'
        approved.write_bytes(original)
        run('restored', 0)
        body = source / 'src/Serilog/Log.cs'
        body.write_text(body.read_text().replace('public static bool IsEnabled(LogEventLevel level) => Logger.IsEnabled(level);', 'public static bool IsEnabled(LogEventLevel level) => false;'))
        edited = run('body-edit', 1)
        assert edited['runtimeHashes'] != cold['runtimeHashes']
        assert run('body-recovered', 0)['runtimeHashes'] == edited['runtimeHashes']
        if reuse:
            assert not edited['preparation']['reused']
            if incremental_sources:
                assert edited['preparation']['packagePayloadReused']
                assert not edited['preparation']['discoveryExecuted']
            pointer = json.loads((state / 'preparation/current.json').read_text())
            payload = state / 'preparation/generations' / pointer['generation'] / 'payload'
            (payload / 'entry.json').write_text('corrupt')
            repaired = run('corrupt-plan', 0)
            assert not repaired['preparation']['reused']
            extra = source / 'src/Serilog/NativeNamespaceProbe.cs'
            extra.write_text('namespace Serilog; internal static class NativeNamespaceProbe { internal static int Value => 42; }')
            changed = run('new-source', 2)
            assert not changed['preparation']['reused']
            assert run('unchanged-again', 0)['preparation']['reused']
            pointer = (state / 'cache.json').read_bytes()
            real_generate = native_workflow.generate
            def mutate_lease(plan, view, generated, tests, seeds):
                result = real_generate(plan, view, generated, tests, seeds)
                changed_input = view / 'src/Serilog/Log.cs'
                changed_input.write_bytes(changed_input.read_bytes() + b'\n// mutate accepted lease\n')
                return result
            with patch('native_workflow.generate', side_effect=mutate_lease):
                try: workflow.run(output / 'lease-mutation', operation='test', force_tests=True)
                except ValueError as error: assert 'changed during consumption' in str(error), str(error)
                else: raise AssertionError('accepted lease mutation published')
            assert (state / 'cache.json').read_bytes() == pointer
            cases.append(dict(label='lease-mutation', rejected=True, publicationChanged=False))
            package = source / '.nuget/packages/shouldly/4.2.1/buildTransitive/Shouldly.targets'
            package_bytes = package.read_bytes(); package.write_bytes(package_bytes + b'\n<!-- changed -->\n')
            try:
                try: workflow.run(output / 'changed-package', operation='test', force_tests=True)
                except (ValueError, RuntimeError) as error:
                    assert any(word in str(error).lower() for word in ('package', 'hash', 'payload', 'stale')), str(error)
                else: raise AssertionError('changed package accepted')
                assert (state / 'cache.json').read_bytes() == pointer
                cases.append(dict(label='changed-package', rejected=True))
            finally: package.write_bytes(package_bytes)
            approved.unlink()
            try: workflow.run(output / 'missing-test-data', operation='test', force_tests=True)
            except ValueError as error: assert 'test data' in str(error)
            else: raise AssertionError('missing test data accepted')
            assert (state / 'cache.json').read_bytes() == pointer
            cases.append(dict(label='missing-test-data', rejected=True))
        report = dict(accepted=True, revision=REVISION, cases=cases)
        (output / 'report.json').write_text(json.dumps(report, indent=2))
    finally:
        subprocess.run([str(BAZEL), '--nohome_rc', '--noworkspace_rc', '--output_base=' + str(state / 'b'),
            '--output_user_root=' + str(state / 'u'), 'shutdown'], cwd=state / 'g', check=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'packages', 'output'): p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--reuse', action='store_true')
    p.add_argument('--incremental-sources', action='store_true')
    a = p.parse_args(); probe(a.source, a.packages, a.output, reuse=a.reuse, incremental_sources=a.incremental_sources)
