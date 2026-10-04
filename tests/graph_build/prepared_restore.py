"""Explicit Restore artifacts reuse body edits and reject stale or corrupt inputs."""

import json
import os
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ENV, RUNNER, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-prepared-restore-') as temporary:
        work = Path(temporary).resolve()
        root = work / 'workspace'
        root.mkdir()
        contract = fixture(root)
        contract['Properties']['DisableTransitiveProjectReferences'] = 'true'
        outputs = [str(p.relative_to(root)) for p in root.glob('P*/obj/*') if p.is_file()]
        for i in range(3):
            declaration = contract['Projects'][f'P{i}/P{i}.csproj']
            declaration['Inputs'] = [p for p in declaration['Inputs'] if '/obj/' not in p]
            declaration['ReferenceBoundary'] = True
            declaration['DependencyCopies'] = {
                f'P{i}/bin/Release/net10.0/P{d}.{ext}': f'P{d}/bin/Release/net10.0/P{d}.{ext}'
                for d in range(i) for ext in ['dll', 'pdb']}
            shutil.rmtree(root / f'P{i}/obj')
        project = root / 'P2/P2.csproj'
        project.write_text(project.read_text().replace('</Project>',
            '<Target Name="PrepareExtra" BeforeTargets="Restore">'
            '<ReadLinesFromFile File="data.txt"><Output TaskParameter="Lines" ItemName="_Data" /></ReadLinesFromFile>'
            '<WriteLinesToFile File="obj/restore.extra.txt" Lines="@(_Data)" Overwrite="true" />'
            '</Target></Project>'))
        data = root / 'P2/data.txt'
        data.write_text('custom restore input')
        contract['Projects']['P2/P2.csproj']['Inputs'] += ['P2/data.txt', 'P2/obj/restore.extra.txt']
        contract['Restore'] = {'Inputs': ['Directory.Build.props', 'P2/data.txt'] + list(contract['Projects']),
                               'Outputs': outputs + ['P2/obj/restore.extra.txt']}
        manifest = work / 'contract.json'
        manifest.write_text(json.dumps(contract))
        prepared = work / 'prepared'
        report = work / 'report.json'
        run(DOTNET, RUNNER, 'prepare', root, manifest, report, prepared)
        assert (prepared / 'manifest.json').is_file()
        assert (prepared / 'P2/obj/restore.extra.txt').read_text().strip() == data.read_text()
        if os.name != 'nt':
            for path in prepared.rglob('*'):
                if path.is_file():
                    path.chmod(0o555)  # Bazel tree-artifact permission normalization.
        ENV['RULES_MSBUILD_GRAPH_PREPARED_RESTORE'] = str(prepared)
        try:
            def build(hits=None, failure=None):
                for i in range(3):
                    shutil.rmtree(root / f'P{i}/bin', ignore_errors=True)
                    shutil.rmtree(root / f'P{i}/obj/Release', ignore_errors=True)
                result = run(DOTNET, RUNNER, 'action', root, manifest, report, work / 'cache', success=failure is None)
                if failure:
                    assert failure in result.stderr, result.stderr
                    return
                measured = json.loads(report.read_text())
                assert measured['preparedRestore'] and measured['hits'] == hits, measured
                return measured
            build(0)
            (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; }')
            build(2)
            # Recover the complete Restore outputs without running Restore again.
            for path in contract['Restore']['Outputs']:
                (root / path).unlink()
            build(3)
            assert run(DOTNET, root / 'P2/bin/Release/net10.0/P2.dll').stdout.strip() == '2'
            data.write_text('changed custom input')
            build(failure='Prepared Restore inputs changed')
            data.write_text('custom restore input')
            archive = root / '.package-source/changed.nupkg'
            archive.write_bytes(b'changed package')
            build(failure='Prepared Restore inputs changed')
            archive.unlink()
            contract['Properties']['Configuration'] = 'Debug'
            manifest.write_text(json.dumps(contract))
            build(failure='Prepared Restore inputs changed')
            contract['Properties']['Configuration'] = 'Release'
            manifest.write_text(json.dumps(contract))
            ENV['RESTORE_CONTRACT_TEST'] = 'different environment'
            build(failure='Prepared Restore inputs changed')
            del ENV['RESTORE_CONTRACT_TEST']
            payload = prepared / 'P0/obj/project.assets.json'
            original = payload.read_bytes()
            payload.chmod(0o755)
            payload.write_bytes(b'corrupt')
            build(failure='Invalid prepared Restore file')
            payload.write_bytes(original)
            # Put a valid output first and each bad entry last. Verification must
            # finish before even that first output is published to the workspace.
            prepared_manifest = prepared / 'manifest.json'
            original_manifest = prepared_manifest.read_bytes()
            records = json.loads(original_manifest)
            valid = contract['Restore']['Outputs'][0]
            for path in contract['Restore']['Outputs']:
                (root / path).unlink()
            def reject_payload(changed, failure):
                changed['Files'] = {valid: records['Files'][valid], **{
                    path: record for path, record in changed['Files'].items() if path != valid}}
                prepared_manifest.chmod(0o644)
                prepared_manifest.write_text(json.dumps(changed))
                report.unlink(missing_ok=True)
                build(failure=failure)
                assert not report.exists(), 'Failed verification produced a build report'
                assert not any((root / path).exists() for path in contract['Restore']['Outputs']), \
                    'Verification failure wrote Restore outputs'
            changed = json.loads(original_manifest)
            invalid_mode = prepared / '.nuget/invalid/mode'
            invalid_mode.parent.mkdir(parents=True)
            invalid_mode.write_bytes((prepared / valid).read_bytes())
            changed['Files']['.nuget/invalid/mode'] = dict(records['Files'][valid], Mode=0x1000)
            reject_payload(changed, 'Invalid prepared Restore file')
            invalid_mode.unlink()
            changed = json.loads(original_manifest)
            changed['Files']['../escape'] = records['Files'][valid]
            reject_payload(changed, 'Expected a workspace-relative path')
            changed = json.loads(original_manifest)
            changed['Files']['undeclared.txt'] = records['Files'][valid]
            (prepared / 'undeclared.txt').write_bytes((prepared / valid).read_bytes())
            reject_payload(changed, 'Invalid prepared Restore file')
            (prepared / 'undeclared.txt').unlink()
            changed = json.loads(original_manifest)
            changed['Files'].pop(contract['Restore']['Outputs'][-1])
            reject_payload(changed, 'Prepared Restore is missing a declared output')
            # Same-size, same-mtime corruption cannot be hidden by metadata reuse.
            last = contract['Restore']['Outputs'][-1]
            last_payload = prepared / last
            last_bytes, last_stat = last_payload.read_bytes(), last_payload.stat()
            last_payload.chmod(0o644)
            last_payload.write_bytes(bytes([last_bytes[0] ^ 1]) + last_bytes[1:])
            os.utime(last_payload, ns=(last_stat.st_atime_ns, last_stat.st_mtime_ns))
            reject_payload(json.loads(original_manifest), 'Invalid prepared Restore file')
            last_payload.write_bytes(last_bytes)
            # An existing destination is independently verified before reuse.
            (root / valid).parent.mkdir(parents=True, exist_ok=True)
            (root / valid).write_bytes(b'conflicting output')
            prepared_manifest.write_bytes(original_manifest)
            build(failure='Prepared Restore conflicts with existing workspace file')
            (root / valid).unlink()
            if os.name != 'nt':
                link = prepared / '.nuget/link/payload'
                link.parent.mkdir(parents=True)
                link.symlink_to(prepared / valid)
                changed = json.loads(original_manifest)
                changed['Files']['.nuget/link/payload'] = records['Files'][valid]
                reject_payload(changed, 'Symlinks are not supported')
                link.unlink()
            prepared_manifest.write_bytes(original_manifest)
            build(3)
            relocated = work / 'relocated'
            shutil.copytree(root, relocated)
            result = run(DOTNET, RUNNER, 'action', relocated, manifest, report, work / 'cache', success=False)
            assert 'Prepared Restore inputs changed' in result.stderr, result.stderr
            contract['Restore']['Inputs'].remove('Directory.Build.props')
            manifest.write_text(json.dumps(contract))
            build(failure='Restore inputs must include every project, definition and shared input')
            print('PASS: prepared Restore, body reuse, fresh output recovery, stale inputs, byte/mode/path/manifest/conflict controls before output writes, and unsafe relocation rejection')
        finally:
            ENV.pop('RULES_MSBUILD_GRAPH_PREPARED_RESTORE', None)
            ENV.pop('RESTORE_CONTRACT_TEST', None)


if __name__ == '__main__':
    main()
