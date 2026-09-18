"""Compare all exported payload bytes and modes across accepted workflow runs."""
import argparse
import hashlib
import json
from pathlib import Path
import stat


def payload(root):
    return {str(p.relative_to(root)): dict(size=p.stat().st_size,
            sha256=hashlib.sha256(p.read_bytes()).hexdigest(), mode=stat.S_IMODE(p.stat().st_mode))
            for p in sorted(root.rglob('*')) if p.is_file()}


def bundles(root):
    result = {}
    for bundle in root.iterdir():
        metadata = json.loads((bundle / 'results.json').read_text())
        seal = json.loads((bundle / 'bundle.json').read_text())
        for field, name in [('resultsSha256', 'results.json'), ('artifactsSha256', 'artifacts.json')]:
            assert seal[field] == hashlib.sha256((bundle / name).read_bytes()).hexdigest()
        artifacts = json.loads((bundle / 'artifacts.json').read_text())
        actual = payload(bundle / 'artifacts')
        assert {a['path']: (a['size'], a['sha256']) for a in artifacts} == {
            name: (item['size'], item['sha256']) for name, item in actual.items()}
        assert metadata['project'] not in result
        # Keys/toolchain identify the changed controller. Compare the declared
        # artifact contract and replay targets independently of those identities.
        result[metadata['project']] = dict(artifacts=actual, targets=metadata['targets'])
    return result


def compare(before, after):
    left = json.loads(before.read_text()); right = json.loads(after.read_text())
    assert left['accepted'] and right['accepted']
    cases = lambda report: {(s['kind'], s['case'], s['repetition']) for s in report['samples']}
    assert cases(left) == cases(right)
    results = []
    for kind, case, repetition in sorted(cases(left)):
        relative = Path(kind) / (case + '-' + str(repetition)) / 'n/state/g/bazel-bin/build.bundle'
        a = before.parent / relative; b = after.parent / relative
        assert payload(a/'app') == payload(b/'app'), (kind, case, 'app')
        for folder in ('cache', 'runtime'):
            assert bundles(a/folder) == bundles(b/folder), (kind, case, folder)
        results.append(dict(kind=kind, case=case, repetition=repetition, app=True, cache=True, runtime=True))
    return dict(accepted=True, beforeRevision=left['revision'], afterRevision=right['revision'], samples=results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path); parser.add_argument('after', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(compare(args.before, args.after), indent=2) + '\n')
