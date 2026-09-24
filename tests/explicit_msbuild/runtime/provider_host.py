"""Prepare a small corerun test using an existing pinned runtime source graph.

No installed runtime payload is included: CoreCLR, JIT, corerun, CoreLib and
System.Runtime come from the prepared graph's declared source-build actions.
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('prepared', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
source = a.prepared.resolve()
metadata = json.loads((source/"native/acquisition.json").read_text())
assert metadata["commit"] == "60629d14374c56f1cb51819049ad1fa529307f8d", "Requires the pinned v10.0.0 qualification graph"
a.output.mkdir(parents=True)
w = a.output.resolve()
for name in ['upstream', 'native', 'native_support']:
    (w/name).symlink_to(source/name, target_is_directory=True)
module = (source/'MODULE.bazel').read_text()
module = re.sub(r'local_path_override\(module_name="rules_msbuild",path="[^"]+"\)',
                'local_path_override(module_name="rules_msbuild",path='+json.dumps(str(ROOT))+')', module)
(w/'MODULE.bazel').write_text(module + '\nbazel_dep(name="platforms", version="1.0.0")\n')
package = w/'runtime'
package.mkdir()
(package/'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
(package/'Program.cs').write_text('''return System.Environment.Version.Major == 10
    && typeof(object).Assembly.Location.Contains("core_runtime.layout")
    && System.Environment.GetEnvironmentVariable("RUNTIME_PROVIDER") == "source"
    && System.IO.File.ReadAllText(System.IO.Path.Combine(System.IO.Path.GetDirectoryName(typeof(object).Assembly.Location)!, "runtime-state.txt")) == "valid"
    ? 0 : 23;
''')
(package/'runtime-state.txt').write_text('valid')
(package/'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_layout", "msbuild_runtime", "msbuild_test")
msbuild_layout(name="core_runtime", paths={
    "runtime-state.txt": "runtime-state.txt",
    "//native:host": "corerun",
    "//native:coreclr": "libcoreclr.so",
    "//native:jit": "libclrjit.so",
    "//native_support:system_native": "libSystem.Native.so",
    "//upstream:src_coreclr_System.Private.CoreLib_System.Private.CoreLib_net10.0": ".",
    "//upstream:src_libraries_System.Runtime_src_System.Runtime_net10.0": ".",
})
msbuild_runtime(name="source_runtime", layout=":core_runtime", entry_point="corerun",
    launch_mode="corerun", runtime_identifier="linux-arm64", version="10.0.0",
    env={"RUNTIME_PROVIDER": "source"},
    target_compatible_with=["@platforms//os:linux", "@platforms//cpu:aarch64"])
msbuild_test(name="smoke", project="App.csproj", srcs=["Program.cs"],
    target_framework="net10.0", use_apphost=False, linux_worker=True,
    runtime_host=":source_runtime")
''')
print(w)
