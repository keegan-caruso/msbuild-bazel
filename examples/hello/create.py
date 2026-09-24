"""Copy the checked-in example into a new standalone Bazel workspace."""
import argparse
import json
from pathlib import Path
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path)
args = parser.parse_args()
example = Path(__file__).resolve().parent
root = example.parents[1]
workspace = args.directory.resolve()
workspace.mkdir(parents=True, exist_ok=False)
for directory in ['Library', 'App']:
    shutil.copytree(example / directory, workspace / directory,
                    ignore=shutil.ignore_patterns('bin', 'obj', 'bazel-*'))
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
print(workspace)
