"""A partial replay must satisfy a cached dependency's initial targets."""

import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, RUNNER, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-initial-targets-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        contract = fixture(root)
        targets = root / 'Directory.Build.targets'
        targets.write_text(
            '<Project InitialTargets="ValidateOnce;SkippedValidation"><Target Name="ValidateOnce">'
            '<Error Condition="Exists(\'$(IntermediateOutputPath)validated.txt\')" '
            'Text="Initial target repeated after replay" />'
            '<MakeDir Directories="$(IntermediateOutputPath)" />'
            '<WriteLinesToFile File="$(IntermediateOutputPath)validated.txt" Lines="validated" />'
            '</Target><Target Name="SkippedValidation" Condition="false">'
            '<Error Text="Changed initial condition executed" /></Target></Project>')
        contract['SharedInputs'].append('Directory.Build.targets')
        manifest = base / 'contract.json'
        manifest.write_text(json.dumps(contract))
        report = base / 'report.json'
        cache = base / 'cache'

        def build(hits, expected):
            for project in contract['Projects'].values():
                for directory in project['OutputDirectories']:
                    shutil.rmtree(root / directory, ignore_errors=True)
            run(DOTNET, RUNNER, 'build', root, manifest, report, cache)
            result = json.loads(report.read_text())
            assert (result['hits'], result['misses']) == (hits, 3 - hits), result
            assert run(DOTNET, root / 'P2/bin/Release/net10.0/P2.dll').stdout.strip() == expected

        build(0, '1')
        build(3, '1')
        (root / 'P2/Code.cs').write_text('System.Console.WriteLine(P1.Value() + 1);')
        build(2, '2')
        build(3, '2')
        for path in cache.glob('*/manifest.json'):
            names = [target['Name'] for target in json.loads(path.read_text())['Targets']]
            assert names.count('ValidateOnce') == 1, names
            assert names.count('SkippedValidation') == 1, names
        # Changed validation logic must invalidate every project, rather than
        # reusing a previously successful initial target result.
        # Change an executed task input, without changing the target names.
        targets.write_text(targets.read_text().replace('Lines="validated"', 'Lines="changed"'))
        build(0, '2')
        targets.write_text(targets.read_text().replace('Condition="false"', 'Condition="true"'))
        for project in contract['Projects'].values():
            for directory in project['OutputDirectories']:
                shutil.rmtree(root / directory, ignore_errors=True)
        failure = run(DOTNET, RUNNER, 'build', root, manifest, report, cache, success=False)
        assert 'Changed initial condition executed' in failure.stdout + failure.stderr
        print('PASS: initial-target replay, partial consumer edit and validation-input invalidation')


if __name__ == '__main__':
    main()
