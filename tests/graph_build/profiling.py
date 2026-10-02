"""Profiling is opt-in and does not change cache identity or replay outputs."""
import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ENV, RUNNER, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-profile-') as temporary:
        work = Path(temporary).resolve()
        root = work / 'workspace'
        root.mkdir()
        contract = fixture(root)
        manifest = work / 'contract.json'
        manifest.write_text(json.dumps(contract))
        report = work / 'report.json'
        ENV.pop('RULES_MSBUILD_GRAPH_PROFILE', None)
        ENV.pop('RULES_MSBUILD_GRAPH_EVALUATION_PROFILE', None)
        run(DOTNET, RUNNER, 'build', root, manifest, report, work / 'cache')
        first = json.loads(report.read_text())
        assert first['operations'] is None and first['materialization'] is None and first['evaluationProfile'] is None
        expected = {str(p.relative_to(root)): p.read_bytes() for p in root.glob('P*/bin/Release/net10.0/*.dll')}
        for item in contract['Projects'].values():
            for path in item['OutputDirectories']:
                shutil.rmtree(root / path)
        ENV['RULES_MSBUILD_GRAPH_PROFILE'] = '1'
        run(DOTNET, RUNNER, 'build', root, manifest, report, work / 'cache')
        phases_only = json.loads(report.read_text())
        assert phases_only['operations'] and phases_only['evaluationProfile'] is None, phases_only
        assert phases_only['hits'] == 3 and phases_only['misses'] == 0, phases_only
        for item in contract['Projects'].values():
            for path in item['OutputDirectories']:
                shutil.rmtree(root / path)
        ENV['RULES_MSBUILD_GRAPH_EVALUATION_PROFILE'] = '1'
        run(DOTNET, RUNNER, 'build', root, manifest, report, work / 'cache')
        result = json.loads(report.read_text())
        assert result['hits'] == 3 and result['misses'] == 0, result
        assert result['operations']['snapshotValidation']['calls'] == 3
        assert result['evaluationProfile']['configuredProjects'] == 3, result
        assert result['evaluationProfile']['profiledProjects'] == 3, result
        assert result['evaluationProfile']['importRecords'] > result['evaluationProfile']['distinctImports'] > 0, result
        phases = ['evaluationSetup', 'projectEvaluation', 'configurationSelection', 'inputPathValidation',
                  'nodeValidation', 'outputOwnershipValidation', 'outputOwnershipIndex']
        assert all(result['operations'][phase]['calls'] == 1 for phase in phases), result
        assert sum(result['operations'][phase]['seconds'] for phase in phases) <= result['evaluationSeconds'] + .01, result
        assert result['operations']['projectLoad']['calls'] == result['operations']['projectInstance']['calls'] == 3, result
        assert result['operations']['msbuildEvaluation/TotalEvaluation']['calls'] == 3, result
        assert result['operations']['fileHash']['bytes'] > 0
        assert result['materialization']['bytes'] > 0
        assert sum(result[key] for key in ['restoreSeconds', 'evaluationSeconds', 'inputHashSeconds', 'executionSeconds', 'verificationSeconds', 'snapshotSeconds']) <= result['totalSeconds'] + .01
        assert expected == {str(p.relative_to(root)): p.read_bytes() for p in root.glob('P*/bin/Release/net10.0/*.dll')}
        print('PASS: profiling default, cache identity, disjoint phases, counters and output parity')


if __name__ == '__main__':
    main()
