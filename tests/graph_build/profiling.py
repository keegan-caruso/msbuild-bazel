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
        run(DOTNET, RUNNER, 'build', root, manifest, report, work / 'cache')
        first = json.loads(report.read_text())
        assert first['operations'] is None and first['materialization'] is None
        expected = {str(p.relative_to(root)): p.read_bytes() for p in root.glob('P*/bin/Release/net10.0/*.dll')}
        for item in contract['Projects'].values():
            for path in item['OutputDirectories']:
                shutil.rmtree(root / path)
        ENV['RULES_MSBUILD_GRAPH_PROFILE'] = '1'
        run(DOTNET, RUNNER, 'build', root, manifest, report, work / 'cache')
        result = json.loads(report.read_text())
        assert result['hits'] == 3 and result['misses'] == 0, result
        assert result['operations']['snapshotValidation']['calls'] == 3
        assert result['operations']['fileHash']['bytes'] > 0
        assert result['materialization']['bytes'] > 0
        assert sum(result[key] for key in ['restoreSeconds', 'evaluationSeconds', 'inputHashSeconds', 'executionSeconds', 'verificationSeconds', 'snapshotSeconds']) <= result['totalSeconds'] + .01
        assert expected == {str(p.relative_to(root)): p.read_bytes() for p in root.glob('P*/bin/Release/net10.0/*.dll')}
        print('PASS: profiling default, cache identity, disjoint phases, counters and output parity')


if __name__ == '__main__':
    main()
