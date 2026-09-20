"""Fresh Orchard gated/direct cache comparison, then producer-deleted recovery."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from cache_service import CacheService
from readonly_package_workflow_probe import application_check
from workload import ROOT, remove, shutdown


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    original = json.loads(args.request.read_text())
    records = []
    expected = None
    state = output / 'state'
    for mode in ['gated', 'direct']:
        with CacheService(args.cache_binary, output / (mode + '-cache'), max_size=8) as cache:
            for recovery in ([False, True] if mode == 'direct' else [False]):
                label = mode + ('-recovery' if recovery else '')
                result = output / label
                result.mkdir()
                request = dict(original, repository=str(ROOT), state=str(state), output=str(result / 'workflow'))
                request.update({'borrow-package-inputs': True, 'action-local-validation': True,
                                'experimental-direct-action-cache': mode == 'direct',
                                'bazel-remote-cache': cache.url, 'bazel-remote-upload': not recovery})
                path = result / 'request.json'
                path.write_text(json.dumps(request, indent=2))
                try:
                    with (result / 'command.log').open('w') as log:
                        process = subprocess.run([str(Path(request['sdkRoot']) / 'dotnet'),
                            str(ROOT / 'tools/Preparation/bin/Release/net10.0/Preparation.dll'),
                            'owned-workflow', '--request', str(path)], cwd=ROOT,
                            stdout=log, stderr=subprocess.STDOUT, timeout=2400)
                    report = json.loads((result / 'workflow/report.json').read_text())
                    assert process.returncode == 0 and report['accepted'], label
                    assert report['compiles'] == (0 if recovery else args.projects), report['compiles']
                    assert report['cachePublication'] == ('action-experimental' if mode == 'direct' else 'workflow-gated')
                    binary = state / 'g/bazel-bin'
                    app = binary / 'build.bundle/app'
                    hashes = {str(p.relative_to(app)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in app.rglob('*') if p.is_file()}
                    (result / 'application-hashes.json').write_text(json.dumps(hashes, indent=2))
                    if expected is None:
                        expected = hashes
                    elif recovery:
                        assert hashes == expected, [p for p in hashes if hashes[p] != expected.get(p)][:10]
                    else:
                        assert hashes.keys() == expected.keys(), 'Application membership differs'
                        different = {p for p in hashes if hashes[p] != expected[p]}
                        assert all(Path(p).suffix in ('.dll', '.pdb') and
                                   str(Path(p).with_suffix('.pdb' if p.endswith('.dll') else '.dll')) in different
                                   for p in different), sorted(different)
                        (result / 'independent-build-differences.json').write_text(json.dumps(sorted(different), indent=2))
                        expected = hashes
                    if recovery:
                        for mnemonic in ['MsbuildCompileProject', 'MsbuildBindProject', 'MsbuildDiscover', 'MsbuildLockedRestore', 'NugetExtractPackage']:
                            assert report[mnemonic]['executed'] == 0, (label, mnemonic, report[mnemonic])
                        assert not [f for tree in binary.glob('nuget_*.package') for f in tree.rglob('*') if f.is_file()]
                    else:
                        for mnemonic in ['MsbuildCompileProject', 'MsbuildBindProject', 'MsbuildDiscover', 'MsbuildLockedRestore', 'NugetExtractPackage']:
                            assert report[mnemonic]['remoteHits'] == 0, (label, mnemonic)
                        shutil.copy2(binary / 'prepare.diagnostics/report.json', result / 'discovery-profile.json')
                    shutil.copy2(state / 'b/command.profile.gz', result / 'command.profile.gz')
                    record = dict(mode=label, seconds=report['seconds'], compiles=report['compiles'],
                                  phases=report['phases'], applicationFiles=len(hashes),
                                  exactProducerRecovery=recovery,
                                  runtime=application_check(app, result, request['sdkRoot']))
                    records.append(record)
                    (output / 'report.json').write_text(json.dumps(records, indent=2) + '\n')
                    cache.capture(label)
                    print(json.dumps(record), flush=True)
                finally:
                    shutdown(output)
                # Recovery must not depend on producer files, live Bazel state or pending uploads.
                remove(state)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache-binary', type=Path, required=True)
    parser.add_argument('--projects', type=int, default=202)
    run(parser.parse_args())
