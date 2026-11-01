"""Verify matching raw/graph CI work before presenting timing comparisons."""
import argparse
import json
from pathlib import Path


def compare(raw, graph):
    expected_case = 'whole-recovery' if raw['case'] == 'unchanged' else raw['case']
    assert graph['case'] == expected_case
    for key in ['contractSha256', 'editToken', 'sourceEdits', 'signatures', 'outcomes']:
        assert raw[key] == graph[key], key
    compiled = {name: record for name, record in graph['files'].items()
        if Path(name).suffix in ['.dll', '.pdb', '.resources']
        and not (name.startswith('artifacts/obj/') and '/PreTrim/' in name)}
    different = sorted(name for name in raw['files'].keys() | compiled.keys()
        if raw['files'].get(name, {}).get('sha256') != compiled.get(name, {}).get('sha256'))
    assert not different, f'Compiled bytes differ in {len(different)} files: {different[:10]}'
    # Bazel makes managed action outputs read-only/executable. SDK permissions
    # are not the transport policy; producer/consumer mode parity is checked by
    # runtime_recovered_tests before this comparison.
    assert all(record['mode'] in [0o644, 0o744] for record in raw['files'].values()), 'Unexpected raw managed mode'
    assert all(record['mode'] == 0o555 for record in compiled.values()), 'Unexpected Bazel managed output mode'
    assert raw['executedTests'] == 9
    assert graph['executedTests'] + graph['remoteTestHits'] + graph['localTestHits'] == 9
    assert graph['localTestHits'] == 0, 'Fresh-worker comparisons cannot use local test results'
    return dict(case=raw['case'], rawSeconds=raw['commandSeconds'],
        graphSeconds=graph.get('buildAndTestSeconds', graph['commandSeconds']),
        graphInterphaseCheckSeconds=graph.get('interphaseCheckSeconds'),
        rawRestoreSeconds=raw['restoreSeconds'], rawBuildSeconds=raw['buildSeconds'],
        rawPublicationSeconds=raw['publicationSeconds'], rawTestSeconds=raw['testSeconds'],
        graphBuildSeconds=graph['buildSeconds'], graphTestSeconds=graph['testCommandSeconds'],
        graphExecutedTests=graph['executedTests'], graphRemoteTestHits=graph['remoteTestHits'],
        rawExecutedTests=raw['executedTests'], compiledFiles=len(compiled),
        managedModePolicy='raw SDK 0644/0744; Bazel action outputs 0555; graph producer/consumer modes verified separately',
        outcomes=raw['outcomes'], scope=raw['scope'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw', type=Path)
    parser.add_argument('graph', type=Path)
    parser.add_argument('--case', choices=['unchanged', 'body', 'api'], required=True)
    args = parser.parse_args()
    raw = json.loads(args.raw.read_text())
    assert raw['case'] == args.case
    selected = 'whole-recovery' if args.case == 'unchanged' else args.case
    graph, = [row for row in json.loads(args.graph.read_text()) if row['case'] == selected]
    print(json.dumps(compare(raw, graph), indent=2))


if __name__ == '__main__':
    main()
