"""Exercise restore/package invalidation through the real prepared consumer path."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from preparation_reuse import prepared_view
from preparation_identity import tree_snapshot
from probe_bazel import json_stream


def probe(source, output):
    source, output = source.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    state = output / 'state'
    entries = [dict(project='src/Serilog/Serilog.csproj', globalProperties={'Configuration': 'Release', 'TargetFramework': 'net10.0'})]
    report = dict(accepted=False, cases={})

    def save():
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def prepare(name, expected_reuse, execute=False):
        consumer = output / name
        with prepared_view(source, state, consumer, entries) as result:
            assert result['reused'] == expected_reuse, result
            record = dict(preparation=result)
            if execute:
                execution = output / (name + '-execution.json')
                command = [os.environ['RULES_MSBUILD_BAZEL'], '--batch', '--nohome_rc', '--noworkspace_rc',
                    '--output_base=' + str(output / (name + '-base')), 'build', '//:all',
                    '--disk_cache=' + str(output / (name + '-empty-cache')), '--spawn_strategy=darwin-sandbox',
                    '--strategy=MsbuildProject=darwin-sandbox', '--jobs=2', '--noshow_progress',
                    '--execution_log_json_file=' + str(execution)]
                run = subprocess.run(command, cwd=consumer, capture_output=True, text=True, timeout=300)
                (output / (name + '.log')).write_text(run.stdout + run.stderr)
                assert run.returncode == 0, run.stderr[-3000:]
                actions = [r for r in json_stream(execution) if r.get('mnemonic') == 'MsbuildProject']
                assert len(actions) == 1 and not actions[0].get('cacheHit') and actions[0]['runner'] == 'darwin-sandbox', actions
                record['expectedNativeActions'] = record['nativeActions'] = 1
            report['cases'][name] = record
        save()

    def reject(name, path, mutate, expected_diagnostics):
        original = path.read_bytes()
        source_identity = tree_snapshot(source)['sha256']
        # Fresh fallback can update MSBuild's generated assets caches while
        # rejecting bad inputs. Restore those too, so the next case starts
        # from exactly the same content instead of depending on warm-up state.
        generated = {p: p.read_bytes() for p in source.rglob('*')
                     if p.is_file() and 'obj' in p.relative_to(source).parts}
        pointer = (state / 'current.json').read_bytes()
        try:
            mutate(path, original)
            try:
                with prepared_view(source, state, output / name, entries):
                    raise AssertionError('invalid package/restore produced a consumer')
            except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
                # CalledProcessError reports the exporting process failure;
                # its diagnostic is retained in the probe's outer log.
                diagnostic = str(error)
                assert isinstance(error, subprocess.CalledProcessError) or any(s in diagnostic for s in expected_diagnostics), diagnostic
                assert not (output / name).exists(), 'invalid inputs published consumer state'
                assert (state / 'current.json').read_bytes() == pointer, 'invalid inputs changed committed generation'
                report['cases'][name] = dict(rejected=True, diagnostic=diagnostic,
                    committedGenerationPreserved=True, consumerAbsent=True)
        finally:
            path.write_bytes(original)
            for current in source.rglob('*'):
                if current.is_file() and 'obj' in current.relative_to(source).parts and current not in generated:
                    current.unlink()
            for current, data in generated.items():
                current.write_bytes(data)
            assert tree_snapshot(source)['sha256'] == source_identity, 'negative control did not restore source content'
            save()

    assets = source / 'src/Serilog/obj/project.assets.json'
    original_assets = assets.read_bytes()
    try:
        prepare('cold', False)
        prepare('unchanged', True)
        # Valid restore content changes must refresh preparation even when the
        # package graph is semantically the same; consume the refreshed plan.
        assets.write_bytes(original_assets + b'\n')
        prepare('restore-content-refreshed', False, execute=True)
        reject('restore-corrupt', assets, lambda p, data: p.write_text('{'), ('restore', 'assets', 'JSON'))
        package = source / '.nuget/packages/polysharp/1.15.0'
        assembly = package / 'analyzers/dotnet/cs/PolySharp.SourceGenerators.dll'
        reject('package-assembly-corrupt', assembly, lambda p, data: p.write_bytes(data + b'corrupt'), ('hash-mismatch',))
        reject('package-assembly-missing', assembly, lambda p, data: p.unlink(), ('missing', 'hash-mismatch'))
        targets = package / 'buildTransitive/PolySharp.targets'
        reject('package-import-corrupt', targets, lambda p, data: p.write_bytes(data + b'\n'), ('hash-mismatch',))
        # After rejected requests, valid inputs must recover a usable consumer.
        prepare('restored-inputs', True, execute=True)
        prepare('restored-unchanged', True)
        report['accepted'] = True
    finally:
        assets.write_bytes(original_assets)
        save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    probe(args.source, args.output)
