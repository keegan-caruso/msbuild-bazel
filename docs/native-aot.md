# Native AOT: first Linux build

An SDK-style `net10.0` console app can publish a runnable Linux ARM64 Native
AOT executable through a Bazel action. MSBuild owns `Publish` and the
ILCompiler invocation. Bazel owns the project source, SDK, six pinned NuGet
package archives, native toolchain input, and binary output.

## Rule shape

The project sets `RuntimeIdentifier=linux-arm64`, `PublishAot=true`, and
`SelfContained=true`, and defines an export target that depends on `Publish` and
copies its executable to the `NativeBinaryOutput` property. The BUILD declaration
is ordinary `msbuild_generate`:

```starlark
msbuild_generate(
    name = "aot",
    executable = True,
    project = "Hello.csproj",
    srcs = ["Program.cs"],
    target_framework = "net10.0",
    targets = ["ExportAot"],
    outputs = ["Hello"],
    output_properties = {"NativeBinaryOutput": "Hello"},
    package_lock = ":aot_lock",
    build_deps = [":compiler", ":compiler_runtime", ":nativeaot_runtime", ":runtime_pack", ":aspnet_runtime_pack", ":illink"],
    native_toolchain = ":linux_aot_toolchain",
)
```

Each `build_deps` entry is a `msbuild_nuget_package` with its archive SHA-256,
NuGet content hash, ID and version declared. The exact six packages chosen by
SDK 10.0.400 for runtime 10.0.11 are in the
[acceptance fixture](../tests/explicit_msbuild/native_aot.py). Removing the
ILCompiler package makes the closed restore fail with `NU1100`.

`native_toolchain` must be a single Bazel tree artifact with `usr/` and
`etc/` directories. Its `usr/` and `etc/` are mounted read-only at those
paths inside the runner's Bubblewrap namespace. The `/bin` and `/lib` links
resolve into the declared `usr/` tree. Bazel includes the complete tree in the
AOT action's input digest; this action is eligible for action caching. A tree
producer must preserve executable bits and symlinks and provide the native
compiler, linker, headers, C runtime files, zlib development files and symbol
tools that the project uses. The fixture's test-only producer snapshots the
local Ubuntu toolchain without caching that producer action. It is not a pinned
toolchain acquisition rule. The selected Linux C library baseline also matters:
the [.NET deployment guide](https://learn.microsoft.com/en-us/dotnet/core/deploying/native-aot/)
states that a Native AOT binary built on one Linux version runs on that version
or newer, so the Ubuntu 22.04 fixture does not qualify older distributions.

`local_native_tools = True` remains the local qualification option. It exposes
the machine's `/usr` read-only and gives the action `no-cache` and `no-remote`
requirements. Both modes require a fresh action; they cannot be combined or
used with persistent workers. The declared-tree mode is currently Linux-only.

## .NET tooling guidance

The [.NET Native AOT deployment guide](https://learn.microsoft.com/en-us/dotnet/core/deploying/native-aot/)
recommends putting `PublishAot=true` in the project file and publishing for a
specific RID. For Ubuntu it lists `clang` and `zlib1g-dev` as prerequisites;
macOS uses Xcode Command Line Tools and Windows uses the Visual Studio C++
workload. For AOT-compatible libraries, `IsAotCompatible=true` enables the
trimming and AOT analyzers. The fixture keeps `PublishAot` in its project file.

The [runtime's AOT development guide at v10.0.0](https://github.com/dotnet/runtime/blob/v10.0.0/docs/workflow/building/coreclr/nativeaot.md)
describes ILC producing an object file, then a platform linker combining it
with the NativeAOT runtime library. It distinguishes a fast local
`build.sh clr.aot+libs -rc Release -lc Release` build from a Release build
that creates NuGet packages. Its direct compiler/framework path overrides
(`IlcToolsPath`, `IlcSdkPath`, `IlcFrameworkPath`,
`IlcFrameworkNativePath`, `IlcMibcPath`) require a closely matching SDK.
The [advanced compiling guide](https://github.com/dotnet/runtime/blob/v10.0.0/src/coreclr/nativeaot/docs/compiling.md)
prefers the SDK-selected `Microsoft.DotNet.ILCompiler` version for ordinary
apps. The fixture follows that recommendation: it locks the packages selected
by SDK 10.0.400 but does not add a direct package reference to the project.

For **building the runtime toolchain from source**, the
[CoreCLR build guide at v10.0.0](https://github.com/dotnet/runtime/blob/v10.0.0/docs/workflow/building/coreclr/README.md#build-drivers)
supports Ninja as the native build driver. Ninja is the Windows default and
recommended there; on Linux and macOS, `build.sh -subset clr -ninja` selects
it instead of the default Make driver. This is a choice for building native
runtime components, not a prerequisite for `dotnet publish` of an AOT app.
The `clr.aot+libs` and `-ninja` combination has not been qualified here.

For cross-architecture builds, [.NET requires](https://learn.microsoft.com/en-us/dotnet/core/deploying/native-aot/cross-compile)
a target-capable linker, target C runtime and zlib objects, plus compatible
`objcopy` or `strip` when stripping symbols. The runtime's
[container guidance](https://github.com/dotnet/runtime/blob/main/src/coreclr/nativeaot/docs/containers.md)
uses `SysRoot` and `LinkerFlavor=lld` for Linux cross-builds. `SysRoot` points
at target libraries; the host compiler still has to be supplied. .NET does
not support cross-OS Native AOT compilation without emulation. This fixture
qualifies only same-architecture Linux ARM64.

## Measured proof

On the Apple Container Ubuntu 22.04 ARM64 toolchain image, with SDK 10.0.400,
Bazel 9.2.0 and native Linux sandboxing, the acceptance script built an ARM64
ELF executable and ran it successfully. A body edit rebuilt the binary, changed
its SHA-256 from
`2024acd2d33735eb83a9f6e11b0cec10d28966d614572098478712327ff34c79`
to `f0cdfbad3bf96be3a13fd3cfb64b944117e33b1cc942a4ba35e94817d4eb3e7f`,
and changed its output. Omitting the compiler package failed during offline
restore. The [report](native-aot-evidence.json) records these outcomes; it is
one qualification run, not a benchmark.

The declared-tree run produced the same initial and body-edit hashes and
outputs. Removing the SDK-selected ILCompiler package failed closed restore;
removing `clang` and `gcc` from the **declared tree** failed with
`Platform linker ('clang' or 'gcc') not found in PATH` even though both
remained installed on the container host. The test tree occupied 962 MB; it
included broad Ubuntu `usr/bin`, `usr/lib` and `usr/include` directories
to establish correctness, not an optimized distribution. The
[declared-toolchain report](native-aot-toolchain-evidence.json) records these
controls. Independent cache recovery and execution on a machine without
ambient native tools have not yet been measured.

To repeat inside a Linux ARM64 environment with `clang`, `llvm-objcopy`, zlib
headers, the pinned Bazel binary, and a working Bubblewrap namespace:

```sh
export RULES_MSBUILD_BAZEL=/path/to/bazel-9.2.0
python3 tests/explicit_msbuild/native_aot.py /tmp/native-aot-qualification
```

The script fetches the six hash-pinned NuGet archives before constructing its
closed Bazel workspace. `--package-cache /path/to/nuget/packages` reuses a
verified local package cache instead. The resulting binary is
`source/bazel-bin/aot.generated/Hello` under the supplied output directory.
Pass `--declared-toolchain` to run the tree-input qualification; the fixture
producer snapshots the local Ubuntu toolchain, so it is test-only.

## Next boundary

Package a smaller, pinned native toolchain as a Bazel-produced tree and select
it through a Bazel toolchain. Prove independent cache recovery at a new workspace
path and execution on a worker without ambient native tools before claiming
remote-cache or remote-execution correctness. Source-built SDK support also
needs matching ILCompiler, NativeAOT runtime, runtime-pack and ILLink outputs
declared from source. macOS, x64, cross-compilation, dynamic library exports
and ASP.NET AOT remain unqualified.
