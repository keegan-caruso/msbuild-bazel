"""Copy the checked-in example into a new standalone Bazel workspace."""
import argparse
import json
import os
from pathlib import Path
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path)
args = parser.parse_args()
example = Path(__file__).resolve().parent
root = example.parents[1]
sdk = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', root / '.tools/dotnet')).resolve()
runner = root / 'tools/ExplicitBuild/bin/Release/net10.0/ExplicitBuild.dll'
if not (sdk / 'dotnet').is_file():
    parser.error('Install the pinned SDK or set RULES_MSBUILD_DOTNET_ROOT first.')
if not runner.is_file():
    parser.error('Build tools/ExplicitBuild in Release first; see the README.')
workspace = args.directory.resolve()
workspace.mkdir(parents=True, exist_ok=False)
for directory in ['Library', 'App']:
    shutil.copytree(example / directory, workspace / directory,
                    ignore=shutil.ignore_patterns('bin', 'obj', 'bazel-*'))
(workspace / 'MODULE.bazel').write_text(f'''module(name = "hello_msbuild")
bazel_dep(name = "rules_msbuild", version = "0.0.0")
local_path_override(module_name = "rules_msbuild", path = {json.dumps(str(root))})
sdk = use_repo_rule("@rules_msbuild//bazel:msbuild.bzl", "local_dotnet_sdk")
sdk(name = "dotnet", path = {json.dumps(str(sdk))}, include_runtime_closure = {str(str(sdk).startswith('/nix/store/'))})
register_toolchains("//:registered")
''')
(workspace / 'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:toolchain.bzl", "msbuild_toolchain")
msbuild_toolchain(
    name = "implementation",
    dotnet = "@dotnet//:sdk/dotnet",
    sdk = "@dotnet//:files",
    runner = "@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",
    runner_support = ["@rules_msbuild//tools/ExplicitBuild:files"],
    runtime_manifest = "@dotnet//:runtime-roots.json",
)
toolchain(
    name = "registered",
    toolchain = ":implementation",
    toolchain_type = "@rules_msbuild//msbuild:toolchain_type",
)
''')
shutil.copyfile(root / '.bazelversion', workspace / '.bazelversion')
print(workspace)
