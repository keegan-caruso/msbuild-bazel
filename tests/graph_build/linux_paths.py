"""Fresh graph actions at unrelated paths share only the remote project cache."""

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from qualify import DOTNET, ROOT, SDK, fixture, run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--projects', type=int, default=3)
    count = parser.parse_args().projects
    assert count >= 3
    assert os.environ.get('RULES_MSBUILD_PROJECT_CACHE_URL'), 'Set a disposable remote cache URL'
    with tempfile.TemporaryDirectory(prefix='graph-linux-paths-') as temporary:
        work = Path(temporary)
        source = work / 'source'
        source.mkdir()
        fixture(source, count)
        # Distinct contract inputs avoid hits from previous invocations.
        with (source / 'Directory.Build.props').open('a') as stream:
            stream.write('<!-- ' + str(uuid.uuid4()) + ' -->')
        sync = ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll'
        run(DOTNET, sync, source, SDK / 'sdk/10.0.400', f'P{count - 1}/P{count - 1}.csproj', '--graph')

        def build(name, hits, value):
            output = work / name / 'output'
            output.mkdir(parents=True)
            shutil.copytree(source, output / 'workspace', ignore=shutil.ignore_patterns('bin', 'obj'))
            scratch = work / name / 'scratch'
            scratch.mkdir()
            run('bash', ROOT / 'msbuild/graph-sandbox.sh', SDK,
                ROOT / 'tools/GraphBuild/bin/Release/net10.0', output,
                source / 'graph.generated.json', scratch, 'Build')
            report = json.loads((output / 'report.json').read_text())
            assert report['hits'] == hits, (name, report)
            assert run(DOTNET, output / f'workspace/P{count - 1}/bin/Release/net10.0/P{count - 1}.dll').stdout.strip() == value
            print(name, json.dumps(report), flush=True)

        build('producer', 0, '1')
        build('relocated-consumer', count, '1')
        (source / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; }')
        build('body-edit', count - 1, '2')
        (source / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; public static int Added() => 3; }')
        build('api-edit', 0, '2')
        print('PASS: relocated remote replay and dependency body/API invalidation')


if __name__ == '__main__':
    main()
