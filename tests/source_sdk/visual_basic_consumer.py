"""Run the mixed VB/C# integration fixture with the full Linux ARM64 VMR 11 SDK."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from source_action_recovery import actions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sdk_archive', type=Path)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    archive = args.sdk_archive.resolve(strict=True)
    output = args.directory.resolve()
    output.mkdir(parents=True, exist_ok=False)
    rules = Path(__file__).resolve().parents[2]
    integration = rules / 'tests/integration'
    fixture = output / 'fixture'
    shutil.copytree(integration / 'fixtures/visual_basic', fixture)
    for project in [fixture / 'App/App.csproj', fixture / 'Library/Library.vbproj']:
        project.write_text(project.read_text().replace('net10.0', 'net11.0'))
    shutil.copyfile(rules / 'global.json', fixture / 'global.json')
    with (fixture / 'App/Program.cs').open('a') as app:
        app.write('System.Console.WriteLine("VMR_RUNTIME=" + System.Environment.Version);\n')

    module = fixture / 'MODULE.bazel'
    prefix, _ = module.read_text().split('dotnet.sdk(', 1)
    module.write_text(prefix + 'dotnet.sdk_archive(name="dotnet", platform="linux-arm64", '
                      'version="11.0.100", runtime_version="11.0.0", '
                      'integrity="sha256-mTdlhJyh+X1kyhoVezQVizfcdfrP9D1BcHNl3Ick7IU=", '
                      f'urls=[{json.dumps(archive.as_uri())}])\n'
                      'use_repo(dotnet, "dotnet")\nregister_toolchains("@dotnet//:all")\n')
    bazel = str(rules / 'scripts/bazel-launcher.sh')
    subprocess.run([bazel, 'build', '//tests/integration:rules_archive'], cwd=rules, check=True)
    env = dict(os.environ, BIT_WORKSPACE_DIR=str(fixture), BIT_BAZEL_BINARY=bazel,
               TEST_TMPDIR=str(output), RULES_ARCHIVE=str(rules / 'bazel-bin/tests/integration/rules.tar'))
    subprocess.run(['bash', str(integration / 'visual_basic.sh')], env=env, check=True)
    for stage, value in [('seed', 1), ('body', 2), ('independent-recovery', 2), ('recovered-edit', 3)]:
        lines = (output / (stage + '.log')).read_text().splitlines()
        assert f'VB:{value}' in lines and 'VMR_RUNTIME=11.0.0' in lines, stage
    graph = [row for row in actions(output / 'independent-recovery.json') if row['mnemonic'] == 'MSBuildGraph']
    assert len(graph) == 1 and graph[0]['cacheHit'], graph
    print('PASS: full VMR SDK, runtime 11.0.0, VB edits, and fresh-base MSBuildGraph disk-cache hit')


if __name__ == '__main__':
    main()
