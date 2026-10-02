"""Owned retained Linux state repairs outputs and recovers interrupted builds."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from qualify import DOTNET, ENV, RUNNER, fixture, run


def main():
    assert os.uname().sysname == 'Linux'
    with tempfile.TemporaryDirectory(prefix='graph-local-state-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        contract = fixture(root)
        contract['Properties']['DisableTransitiveProjectReferences'] = 'true'
        for index in range(3):
            declaration = contract['Projects'][f'P{index}/P{index}.csproj']
            declaration['ReferenceBoundary'] = True
            declaration['DependencyCopies'] = {f'P{index}/bin/Release/net10.0/P{dependency}.{extension}':
                f'P{dependency}/bin/Release/net10.0/P{dependency}.{extension}'
                for dependency in range(index) for extension in ['dll', 'pdb']}
        project = root / 'P0/P0.csproj'
        project.write_text(project.read_text().replace('</Project>',
            '<Target Name="HoldOwnedBuild" AfterTargets="Build" Condition="\'$(PauseOwnedBuild)\' == \'true\'">'
            '<WriteLinesToFile File="$(TargetDir)waiting.marker" Lines="waiting" /><Exec Command="sleep 30" /></Target></Project>'))
        manifest, report, state = base / 'contract.json', base / 'report.json', base / 'state'
        ENV['RULES_MSBUILD_GRAPH_LOCAL_STATE'] = str(state)
        ENV['RULES_MSBUILD_GRAPH_PROFILE'] = '1'
        command = [DOTNET, RUNNER, 'build', root, manifest, report, base / 'cache']
        def build(hits=None, failure=None, target="Build"):
            manifest.write_text(json.dumps(contract))
            result = run(*command, target, success=failure is None)
            if failure:
                assert failure in result.stderr, result.stderr
                return
            measured = json.loads(report.read_text())
            assert measured['hits'] == hits, measured
            assert json.loads((state / 'state.json').read_text())['Complete']
            return measured
        assert not build(0)['retainedState']
        warm = build(3)
        assert warm['retainedState'] and warm['materialization']['copies'] == 0, warm
        assert warm['operations']['retainedOutput']['calls'] > 0
        source = root / 'P0/Code.cs'
        source.write_text('public class P0 { public static int Value() => 2; }')
        body = build(2)
        assert run(DOTNET, root / 'P2/bin/Release/net10.0/P2.dll').stdout.strip() == '2'
        source.write_text('public class P0 { public static int Value() => 2; public static int Extra() => 3; }')
        build(1)
        app = root / 'P2/bin/Release/net10.0/P2.dll'
        app.write_bytes(b'corrupt retained output')
        stale = app.parent / 'obsolete.txt'
        stale.write_text('stale')
        repair = build(3)
        assert repair['materialization']['copies'] >= 1 and not stale.exists()
        assert run(DOTNET, app).stdout.strip() == '2'
        original_mode = app.stat().st_mode & 0o777
        app.chmod(original_mode ^ 0o111)
        build(3)
        assert app.stat().st_mode & 0o777 == original_mode
        producer = root / 'P0/bin/Release/net10.0/P0.dll'
        copied = app.parent / 'P0.dll'
        copied.unlink()
        os.link(producer, copied)
        assert producer.stat().st_ino == copied.stat().st_ino
        build(3)
        assert producer.stat().st_ino != copied.stat().st_ino
        copied.write_bytes(b'consumer overwrite')
        assert producer.read_bytes()[:2] == b'MZ'
        build(3)
        # A new owner cannot adopt unexplained existing outputs.
        ENV['RULES_MSBUILD_GRAPH_LOCAL_STATE'] = str(base / 'unowned')
        build(failure='New graph state requires empty owned outputs')
        ENV['RULES_MSBUILD_GRAPH_LOCAL_STATE'] = str(state)
        # The OS lease rejects a concurrent request and is released by SIGKILL.
        contract['Properties']['PauseOwnedBuild'] = 'true'
        manifest.write_text(json.dumps(contract))
        log = (base / 'interrupted.log').open('w')
        process = subprocess.Popen(list(map(str, command)), env=ENV, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            marker = producer.parent / 'waiting.marker'
            for _ in range(300):
                if marker.exists() or process.poll() is not None:
                    break
                time.sleep(.1)
            assert marker.exists(), (base / 'interrupted.log').read_text()
            rejected = run(*command, success=False)
            assert 'state.lock' in rejected.stderr, rejected.stderr
            ENV['RULES_MSBUILD_GRAPH_LOCAL_STATE'] = str(base / 'other-owner')
            other_owner = run(*command, success=False)
            assert 'state.lock' in other_owner.stderr, other_owner.stderr
            ENV['RULES_MSBUILD_GRAPH_LOCAL_STATE'] = str(state)
            assert not json.loads((state / 'state.json').read_text())['Complete']
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            log.close()
        del contract['Properties']['PauseOwnedBuild']
        recovered = build(3)
        assert not recovered['retainedState'] and not marker.exists()
        # Changing configuration cleans obsolete owned directories before reuse.
        contract['Properties']['Configuration'] = 'Debug'
        for declaration in contract['Projects'].values():
            declaration['OutputDirectories'] = [path.replace('/Release/', '/Debug/') for path in declaration['OutputDirectories']]
            declaration['DependencyCopies'] = {key.replace('/Release/', '/Debug/'): value.replace('/Release/', '/Debug/')
                                              for key, value in declaration['DependencyCopies'].items()}
        changed = build(0)
        assert not changed['retainedState'] and not producer.parent.exists()
        assert run(DOTNET, root / 'P2/bin/Debug/net10.0/P2.dll').stdout.strip() == '2'
        build(0, target='Publish')
        published = build(3, target='Publish')
        assert published['retainedState']
        assert run(DOTNET, root / 'P2/bin/Debug/net10.0/publish/P2.dll').stdout.strip() == '2'
        print(json.dumps({'warm': warm, 'body': body, 'repair': repair, 'interruptedRecovery': recovered}, indent=2))
        print('PASS: retained hits, fresh misses, body/API propagation, corrupt/obsolete output repair, hard-link isolation, ownership rejection, concurrent lease, SIGKILL recovery configuration cleanup and Publish reuse')


if __name__ == '__main__':
    main()
