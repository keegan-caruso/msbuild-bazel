"""Copy the checked-in example into a new standalone Bazel workspace."""
import argparse
import json
from pathlib import Path
import shutil
import os
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path)
parser.add_argument('--sync', action='store_true', help='Generate the library/app graph with bazel run //:sync')
args = parser.parse_args()
example = Path(__file__).resolve().parent
root = example.parents[1]
workspace = args.directory.resolve()
workspace.mkdir(parents=True, exist_ok=False)
for directory in ['Library', 'App']:
    shutil.copytree(example / directory, workspace / directory,
                    ignore=shutil.ignore_patterns('bin', 'obj', 'bazel-*', *(['BUILD.bazel'] if args.sync else [])))
(workspace / 'MODULE.bazel').write_text(f'''module(name = "hello_msbuild")
bazel_dep(name = "rules_msbuild", version = "0.0.0")
local_path_override(module_name = "rules_msbuild", path = {json.dumps(str(root))})
dotnet = use_extension("@rules_msbuild//msbuild:extensions.bzl", "dotnet")
dotnet.sdk(name = "dotnet", global_json = "//:global.json")
use_repo(dotnet, "dotnet")
register_toolchains("@dotnet//:all")
''')
(workspace / 'BUILD.bazel').write_text('exports_files(["global.json"])\n')
shutil.copyfile(root / 'global.json', workspace / 'global.json')
shutil.copyfile(root / '.bazelversion', workspace / '.bazelversion')
if args.sync:
    build = workspace / 'BUILD.bazel'
    authored = 'load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")\nexports_files(["global.json"])\nmsbuild_sync(name="sync", projects=["App/App.csproj"])\n'
    build.write_text(authored)
    bazel = os.environ.get('RULES_MSBUILD_BAZEL', str(root / 'scripts/bazel-launcher.sh'))
    startup = [bazel, '--output_base=' + str(workspace.parent / (workspace.name + '-base'))]
    try:
        subprocess.run(startup + ['run', '//:sync'], cwd=workspace, check=True)
    finally:
        subprocess.run(startup + ['shutdown'], cwd=workspace, check=True)
    build.write_text('load(":projects.generated.bzl", "app_projects")\nload("@rules_msbuild//msbuild:defs.bzl", "msbuild_test")\n' + authored + 'app_projects()\nmsbuild_test(name="Tests",project="App/App.csproj",target_framework="net10.0",srcs=["App/Program.cs"],deps=[":Library_Library"])\n')
print(workspace)
