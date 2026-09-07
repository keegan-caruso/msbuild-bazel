# Two-target Bazel experiment contract

`python3 tools/probe_bazel.py --output ABSENT_DIRECTORY` prepares a copied fixture,
restores NuGet metadata, and builds the replay plugin outside Bazel compilation
actions. It then runs two explicit `msbuild_project` actions, Shared followed by
App. This is a fixture adapter, not a general graph exporter.

Shared receives only its own sources, project and normalized restore metadata,
common imports/configuration, the runner, replay plugin and SDK file inputs.
It captures the explicit six-target dependency contract in a Shared-only graph
build. App receives its sources, both project files for graph evaluation, common
imports, both normalized restore states and Shared's bundle. Shared source files
are deliberately absent from App's declared inputs and scratch workspace.

Each action copies declared inputs into its own fresh scratch workspace. Restore
metadata is expanded from explicit workspace/SDK tokens; compilation does not
restore or download tools. App stages and validates Shared's dependency bundle,
then uses public-API replay with `-graphBuild -isolateProjects`. Shared and App
outputs are separate Bazel tree artifacts. Action reports and logs live in
separate `<target>.diagnostics` outputs excluded from downstream action inputs.
The SDK tree and framework-dependent `ActionRunner` DLL, deps.json and
runtimeconfig.json participate in the action digest. Bazel launches the declared
SDK host directly with the runner DLL. Python is used only by preparation and
tests. The runtime is not yet a hermetic toolchain;
reports and rule configuration record the chosen host runtime. No remote-cache
or remote-execution correctness is claimed.

The harness requires sandbox execution (no automatic local fallback) and writes
Bazel JSON execution logs. Acceptance cases are cold (Shared and App execute),
unchanged (neither), App edit (App only), Shared edit (both), cleared outputs with
the disk cache retained (both restored), and a fresh Bazel output base using the
same disk cache. It asserts execution records, compilation markers, distinct
action workspaces, absence of Shared sources in the App action, and runnable App
output through both the DLL and native app host, preserving executable modes.
A negative undeclared-input probe must fail inside the action sandbox.
Sandbox platform limitations must be reported explicitly, never hidden by a
fallback to local execution.

`--identity-probe` additionally measures imported targets, generated-source data,
explicit build environment, ambient environment exclusion, App restore metadata
and host-identity changes. See [identity findings](action-identity-findings.md).
The rule requires `dotnet`, `sdk`, `runner`, and `host_identity` labels, with
`runner_support` supplying its runtime JSON files. It optionally accepts `build_environment` entries prefixed with `RULES_MSBUILD_INPUT_`. Remote execution
and remote-cache use are disabled; local disk caching remains enabled.

`--package-probe` is mutually exclusive with `--identity-probe`. It prepares exact
versions of a locally authored, checksum-pinned build package before compilation.
The rule accepts `packages` payload labels and an optional `package_manifest`
label. Before MSBuild starts, the runner checks package/restore identities and
payload hashes, then stages the files in its own NuGet root. See the
[package contract](package-input-plan.md) and [findings](package-input-findings.md).

`--staging-probe` is another mutually exclusive mode. It forces fresh compilation
with a separate output base and empty disk cache, then compares every consumer
bundle file hash and executable bit. Shared stages bin outputs and its reference
assembly, rather than its entire obj tree. See [staging findings](staging-findings.md)
for path mapping, metadata canonicalization and the fixture-specific limits.

`--native-runtime-probe` is an opt-in, mutually exclusive Nix mode. Preparation
queries the SDK reference closure and writes `runtime-closure.json`. The
`native_runtime` and `native_manifest` rule inputs declare all inventoried files;
the runner checks completeness, size and SHA-256 before compilation. The runtime
manifest uses schema version 2 with `files` entries containing `path`, `size` and
`sha256`; version 1 manifests must be regenerated. Missing declarations fail
even if store files are still readable on the host. See [runtime findings](native-runtime-findings.md)
for the host OS boundary and retained evidence.

The native repository optionally accepts `overrides`, mapping input labels to
manifest paths, for controlled workspace-copy experiments. The manifest still
validates their bytes. This changes declared inputs without redirecting absolute
Nix loader paths. `trace_runtime = True` enables dyld/glibc loader diagnostics
for the MSBuild child in a separate build action; the `RULES_MSBUILD_TRACE_RUNTIME`
environment marker participates in action identity.
See [runtime integrity findings](native-runtime-integrity-findings.md).

The optional `loader_jit` and `loader_manifest` labels enable the experimental
private runtime. Both are required together with `native_manifest`; the payload
must match the manifest's filename, size and SHA-256. The runner copies the host
and framework to action scratch, substitutes the JIT, and invokes MSBuild
directly there. Loader evidence is kept in diagnostics, never consumer bundles.
See [loaded JIT findings](loader-runtime-findings.md) for the byte variants,
no-fallback control and remaining absolute-path dependencies.

See the [.NET runner experiment](dotnet-runner-findings.md) for the migration
from Python actions and its validation. The action request and consumer bundle
contracts remain the same except that the runner locates its SDK host through
`Environment.ProcessPath` instead of accepting a redundant `dotnet` JSON field.

The runner also requires `build_props` and `build_targets` labels. These declared
MSBuild wrappers import the staged fixture build files before adding action policy.
The runner sets their import paths through environment properties, preserving
replay's global-property identity. See the [review refactor](action-runner-refactor.md).
