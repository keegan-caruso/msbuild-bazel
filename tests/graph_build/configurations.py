"""Multi-target graph contracts must select and own outputs unambiguously."""

import copy
import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, RUNNER, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-configurations-') as temporary:
        directory = Path(temporary).resolve()
        root = directory / 'workspace'
        root.mkdir()
        (root / 'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks>'
            '</PropertyGroup></Project>')
        (root / 'Code.cs').write_text('public class Library { public static int Value() => 1; }')
        run(DOTNET, 'restore', root / 'Library.csproj', '--source', root, '-p:NuGetAudit=false')
        contract = {'Version': 2, 'Entry': 'Library.csproj', 'SdkVersion': '10.0.400',
            'Properties': {'Configuration': 'Release'}, 'SharedInputs': [],
            'Projects': {'Library.csproj': {'Inputs': sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()),
                'OutputDirectories': [], 'Configurations': [
                    {'Properties': {'TargetFramework': framework}, 'Inputs': [],
                     'OutputDirectories': [f'bin/Release/{framework}', f'obj/Release/{framework}'] if framework else []}
                    for framework in ['', 'net10.0', 'net10.0-windows']]}}}
        manifest = directory / 'contract.json'
        report = directory / 'report.json'

        def invoke(value, mode='inspect', success=True):
            manifest.write_text(json.dumps(value))
            return run(DOTNET, RUNNER, mode, root, manifest, report, directory / 'cache', success=success)

        invoke(contract, 'build')
        assert json.loads(report.read_text())['misses'] == 2
        for framework in ['net10.0', 'net10.0-windows']:
            assert (root / f'bin/Release/{framework}/Library.dll').is_file()
        shutil.rmtree(root / 'bin')
        shutil.rmtree(root / 'obj/Release')
        invoke(contract, 'build')
        assert json.loads(report.read_text())['hits'] == 2
        ambiguous = copy.deepcopy(contract)
        ambiguous['Projects']['Library.csproj']['Configurations'].append(
            {'Properties': {'Configuration': 'Release'}, 'Inputs': [], 'OutputDirectories': []})
        assert 'matched 2' in invoke(ambiguous, success=False).stderr
        missing = copy.deepcopy(contract)
        missing['Projects']['Library.csproj']['Configurations'].pop()
        assert 'matched 0' in invoke(missing, success=False).stderr
        overlap = copy.deepcopy(contract)
        overlap['Projects']['Library.csproj']['Configurations'][2]['OutputDirectories'] = ['bin/Release/net10.0']
        assert 'Overlapping output' in invoke(overlap, success=False).stderr
        legacy = copy.deepcopy(contract)
        legacy['Version'] = 1
        assert 'require version 2' in invoke(legacy, success=False).stderr
        shutil.rmtree(root / 'bin')
        shutil.rmtree(root / 'obj')
        (root / 'Directory.Build.props').write_text('<Project><PropertyGroup>'
            '<MSBuildProjectExtensionsPath>$(MSBuildThisFileDirectory)restore/$(MSBuildProjectName)/</MSBuildProjectExtensionsPath>'
            '<DefaultItemExcludes>$(DefaultItemExcludes);restore/**</DefaultItemExcludes>'
            '</PropertyGroup></Project>')
        contract['SharedInputs'] = ['Directory.Build.props']
        contract['Projects']['Library.csproj']['Inputs'] = ['Library.csproj', 'Code.cs']
        invoke(contract, 'action')
        assert json.loads(report.read_text())['misses'] == 2
        assert (root / 'restore/Library/project.assets.json').is_file()
        shutil.rmtree(root / 'bin')
        shutil.rmtree(root / 'obj')
        invoke(contract, 'action')
        assert json.loads(report.read_text())['hits'] == 2
        print('PASS: multi-target build/replay, custom restore layout, configuration rejection controls')


if __name__ == '__main__':
    main()
