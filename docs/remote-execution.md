# Opt-in Linux remote execution

Project rules accept `allow_remote_execution = True`. The default remains local
execution with remote caching. Opting in removes the `no-remote-exec` action
requirement; Bazel selects the executor using its normal execution platform and
strategy configuration. Declare a compatible Linux platform with bubblewrap,
Bash and .NET's OS dependencies. The SDK and ExplicitBuild runner remain declared
Bazel toolchain inputs and are uploaded to the executor.

```starlark
msbuild_library(
    name = "Library",
    project = "Library.csproj",
    target_framework = "net10.0",
    srcs = ["Value.cs"],
    linux_worker = True,
    allow_remote_execution = True,
)
```

`linux_worker` still enables persistent workers for local execution. On a remote
executor the same action uses the runner's one-shot parameter-file path; this
is **not persistent remote MSBuild execution**. The runner retains its inner
bubblewrap sandbox. A remote worker must permit creating that sandbox.

Tests use Bazel's normal `TestRunner` strategy. The new attribute controls project
compilation, not whether a test runs remotely. Every project action in a dependency
closure needs its own opt-in. Layout composition no longer prohibits remote
execution, but its current qualification covers local sandboxes and cache recovery.
Runtime qualification native actions still prohibit remote execution. Do not treat this synthetic result as
remote qualification of the full Orchard or dotnet/runtime graph, arbitrary task
tools, cross-compilation, Windows or Linux x64.

## Acceptance boundary

`tests/explicit_msbuild/remote_execution.py` exercises a library and executable
test with a project dependency, embedded resource and runtime data. It checks:

- Actual remote compilation/test actions, with remote reads disabled initially
  and local fallback disabled throughout.
- Identical local/remote compiler product hashes (Bazel parameter transport files
  are excluded).
- A body edit recompiles only the library, preserves its public reference assembly
  and reruns the dependent test.
- A fresh output base recovers all compilation/test results from remote cache and
  preserves output hashes.
- Wrong runtime data fails the remote test.
- An unavailable executor fails without local compilation.

The qualification worker is a separate Apple Linux ARM64 container based on
`sha256:47a9e2fed01824f5470f26e75a2fb74017acc1967c637e7793be028f31a8aeee`.
Its entire `/opt/rules_msbuild-toolchain` directory was removed before execution;
it has no preinstalled SDK and no host filesystem mounts. The client retains its
SDK for local baseline and repository/toolchain materialization.

All controls passed on **Bazel 8.8.0 and 9.2.0**, using SDK 10.0.400.
See [compact reports and artifact hash](remote-execution-evidence.json). Existing
worker acceptance also passes with the new attribute left at its default. That
container required a child-process reaper to complete Bazel shutdown; the initial
run stopped at shutdown and was not counted as a passing acceptance run.

## SDK-only remote execution

Pass `--download-sdk` to the acceptance harness to select SDK 10.0.400 through
`dotnet.sdk(global_json = "//:global.json")`. This mode needs neither a locally
installed SDK nor a prebuilt runner. Repository acquisition still happens on the
Bazel client; runner bootstrap is a normal declared action sent to the executor.

The SDK-only synthetic passed on Linux ARM64 with **Bazel 8.8.0 and 9.2.0**. With
remote reads and local fallback disabled, execution logs reported `remote` for
`MSBuildRunnerBootstrap`, `DotnetSdkRuntime`, both `MSBuildAssembly` actions and
`TestRunner`. The worker had no `/opt/rules_msbuild-toolchain` installation or host
mounts. Local and remote compiler product hashes matched.

Body-edit invalidation, unchanged reference assembly, remote test failure, fresh
output-base cache recovery, and an unavailable-executor rejection also passed.
Recovery includes the bootstrap/runtime actions, not only project compilation.
See [SDK remote-execution evidence](sdk-remote-execution-evidence.json).

```sh
python3 tests/explicit_msbuild/remote_execution.py /tmp/sdk-remote-check \
  --download-sdk --executor grpc://WORKER_IP:8980 \
  --platform-image 47a9e2fed018-sdk-removed
```

Use the same qualified OS dependencies and nested sandbox permissions as the
existing fixture. This expands SDK acquisition/bootstrap coverage; it does not
qualify a real-project graph, another architecture, or persistent remote workers.

## Reproduce with Buildbarn

The bounded service fixture under `tests/explicit_msbuild/buildbarn` adapts
[Buildbarn's bare deployment](https://github.com/buildbarn/bb-deployments/tree/a35485609467dd70cd44c78b4735e5835061df5a/bare)
under its included Apache-2.0 license. `acquire.py` downloads digest-pinned public
ARM64 images, verifies manifests/layers and extracts only the four server binaries.
`images.json` records their hashes. Run acquisition outside the executor, then copy
the directory into the disposable Linux worker and run `python3 start.py` there.
The service exposes REAPI on port 8980 and the scheduler UI on 7982.
The Apple test container used `--init --masked-path NONE --read-only-path NONE`
so its kernel permitted the nested bubblewrap namespace. Verify this first:
`bwrap --ro-bind / / --unshare-all -- /bin/true`.
Start with eight CPUs and 8 GiB memory; the fixture registers two execution slots.

The fixture is an unauthenticated private qualification service, not a production
hosting configuration. Use it only on an isolated test network. The worker
advertises `ISA=aarch64`, `OSFamily=linux` and
`rules_msbuild_image=47a9e2fed018-sdk-removed`; these identify the manually verified
OS image, not an automatically enforced container-image policy.

From the Linux client with the compiled runner available:

```sh
RULES_MSBUILD_DOTNET_ROOT=/path/to/dotnet \
RULES_MSBUILD_BAZEL=/path/to/bazel-9.2.0 \
python3 tests/explicit_msbuild/remote_execution.py /tmp/fresh-remote-check \
  --executor grpc://WORKER_IP:8980 \
  --platform-image 47a9e2fed018-sdk-removed
```

The harness gives each output-directory name a separate remote instance namespace.
Use a new name for each run. It saves execution logs, command logs and a compact
`report.json`. A failed setup or transport control is not performance evidence;
no remote performance comparison is claimed here.
