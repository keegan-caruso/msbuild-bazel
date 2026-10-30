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
    assert raw['files'] == compiled, 'Compiled bytes or modes differ'
    assert raw['executedTests'] == 9
    assert graph['executedTests'] + graph['remoteTestHits'] + graph['localTestHits'] == 9
    assert graph['localTestHits'] == 0, 'Fresh-worker comparisons cannot use local test results'
    return dict(case=raw['case'], rawSeconds=raw['commandSeconds'], graphSeconds=graph['commandSeconds'],
        rawRestoreSeconds=raw['restoreSeconds'], rawBuildSeconds=raw['buildSeconds'],
        rawPublicationSeconds=raw['publicationSeconds'], rawTestSeconds=raw['testSeconds'],
        graphBuildSeconds=graph['buildSeconds'], graphTestSeconds=graph['testCommandSeconds'],
        graphExecutedTests=graph['executedTests'], graphRemoteTestHits=graph['remoteTestHits'],
        rawExecutedTests=raw['executedTests'], compiledFiles=len(compiled),
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
