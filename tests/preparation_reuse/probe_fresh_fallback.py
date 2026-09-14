"""Verify unsupported authored XML and explicit test requests use fresh preparation."""
import argparse
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from preparation_reuse import prepared_view


def probe(workspace, output):
    workspace, output = workspace.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source'
    shutil.copytree(workspace, source)
    for path in source.rglob('*'):
        if path.is_file() and 'obj' in path.relative_to(source).parts:
            path.write_bytes(path.read_bytes().replace(str(workspace).encode(), str(source).encode()))
    target = source / 'Directory.Build.targets'
    target.write_text('<Project><Target Name="UnqualifiedUnusedTarget"/></Project>')
    entries = [dict(project='App/App.csproj', globalProperties={'Configuration':'Release', 'TargetFramework':'net10.0'})]
    report = dict(accepted=False, cases={})
    try:
        with prepared_view(source, output / 'cache', output / 'xml', entries) as result:
            assert not result['reused'] and result['toolBuildsExecuted'], result
            report['cases']['unsupported-xml'] = result
        assert not (output / 'cache/current.json').exists()
        target.write_text('<Project/>')
        with prepared_view(source, output / 'cache', output / 'tests', entries, tests=[]) as result:
            assert not result['reused'] and result['toolBuildsExecuted'], result
            report['cases']['explicit-tests'] = result
        assert not (output / 'cache/current.json').exists()
        report['accepted'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(probe(args.workspace, args.output), indent=2))
