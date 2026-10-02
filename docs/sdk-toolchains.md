# SDK and runtime artifacts

The Bzlmod `dotnet.sdk` extension acquires a verified pinned SDK archive selected
by exact version or tracked `global.json`. Host-path repositories are unsupported.
Ordinary app developers use [the quickstart](../examples/quickstart/README.md).

`msbuild_sdk` in `msbuild/sdk.bzl` also accepts declared Bazel-produced artifacts:
`dotnet`, `files`, exact `sdk_version`, `runtime_version`, `runtime_identifier`.
It creates artifact-tool bootstrap, execution SDK toolchain, bundled runtime/SDK
host and constrained registration targets. Register `<name>_registered` and
`<name>_runtime_registered`. Files/tree artifacts must share the SDK layout rooted
beside the executable. Analysis receives metadata; execution consumes the bytes.
A source SDK producer uses a separate controller/bootstrap toolchain and must not
depend on the SDK it is producing.

`msbuild_runtime` describes a complete declared execution layout, entry point,
`dotnet` or `corerun` launch mode, identity and non-reserved environment. Applications
and tests use its provider through `runtime_host`, or the compatible registered
SDK runtime. They never fall back to the runner's installed host. VSTest requires
`dotnet`; executable source-host tests can use `corerun`.

A net8 target can run on a later declared host when its authored runtimeconfig and
roll-forward policy allow it. Build target framework, execution SDK and runtime
host are separate choices. This is not arbitrary cross-platform compatibility.

Source-built runtimes are qualified in [the selected runtime graph](runtime-qualification.md).
The [22-component SDK producer](source-sdk.md) is separate. Native tool/archive and
locked Ubuntu package helpers remain available, but the retired per-project
NativeAOT Publish qualification does not establish graph-only NativeAOT support.
See [current gaps](implementation-plan.md#remaining-work).
