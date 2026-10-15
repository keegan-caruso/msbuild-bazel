"""Inspect authored helper/consumer properties and SDK-selected compiler artifacts.

Run on the disposable raw workspace from runtime_jit_raw.py. No project properties
are changed to introduce reference assemblies. Reports stay outside Git.
"""
import argparse
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw', type=Path)
    parser.add_argument('sdk', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    summary = json.loads((args.raw / 'summary.json').read_text())
    stable = '/__rules_msbuild_graph/output/workspace/'
    prefix = ['bash', str(HERE / 'runtime_raw.sh'), str(args.sdk), str(args.raw / 'workspace'), str(args.raw / 'scratch')]
    cases = json.loads((HERE / 'runtime_jit_cases.json').read_text())
    selected = [case for case in cases if 'dependency' in case]
    assert len(selected) == 1
    case = selected[0]
    rows = {}
    for project in [case['dependency']['project'], case['project']]:
        command = prefix + ['msbuild', stable + project, '-t:Rebuild', '-v:q', '-nologo',
            '-getProperty:ProduceReferenceAssembly,TargetRefPath,TargetPath,OutputType,DebugType',
            '-getItem:ReferencePathWithRefAssemblies'] + ['-p:' + key + '=' + value for key, value in summary['properties'].items()]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True)
        payload = json.loads(result.stdout[result.stdout.index('{\n'):])
        rows[project] = dict(properties=payload['Properties'], references=[{key: item.get(key, '') for key in
            ['Identity', 'ReferenceAssembly', 'ReferenceSourceTarget', 'MSBuildSourceProjectFile']}
            for item in payload['Items']['ReferencePathWithRefAssemblies']])
    helper = rows[case['dependency']['project']]['properties']
    assert helper['ProduceReferenceAssembly'] == 'false' and not helper['TargetRefPath'], helper
    references = [item for item in rows[case['project']]['references'] if item['MSBuildSourceProjectFile'] == stable + case['dependency']['project']]
    assert len(references) == 1
    assert references[0]['Identity'] == references[0]['ReferenceAssembly'] == helper['TargetPath'], references
    assert references[0]['ReferenceSourceTarget'] == 'ProjectReference'
    args.output.write_text(json.dumps(rows, indent=2) + '\n')
    print('PASS: authored helper disables reference emission; Csc consumes its implementation DLL', flush=True)


if __name__ == '__main__':
    main()
