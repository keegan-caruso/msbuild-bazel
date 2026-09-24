# Linux checks with Apple containers

Run these commands from the repository root on an Apple silicon Mac with Apple
Container installed and running. Check the service with `container system status`.
The qualified worker platform is Ubuntu 22.04 ARM64.

## Prepare and run

Build the repository-pinned toolchain image, then select its recorded digest:

```sh
bash scripts/build-apple-container-image.sh
export RULES_MSBUILD_CONTAINER_IMAGE="$(cat .cache/apple-container/arm64/image.ref)"
bash scripts/run-apple-container.sh bash -lc '
  bash scripts/dotnet.sh build tools/ExplicitBuild -c Release -warnaserror &&
  python3 tests/explicit_msbuild/acceptance.py /evidence/acceptance
'
```

The image includes the SDK, Bazel, Python and bubblewrap. Rebuild it when pinned
tools or its build inputs change. Downloads and NuGet restores need network access.
For worker-specific checks, use the commands in
[worker qualification](explicit-linux-workers.md#qualification) through the same runner.
The command above exercises default acceptance, not the complete worker suite.

## Files, resources and limits

[run-apple-container.sh](../scripts/run-apple-container.sh) mounts the checkout
read-only, copies sources into `/workspace`, and runs the supplied command there.
It excludes Git metadata, downloaded tools/caches and build outputs. A prebuilt
image supplies tools; without an image override the script installs them in the
pinned Ubuntu base. The base-image path does not install bubblewrap for worker checks.

The container is removed on exit. Write reports to `/evidence` to retain them
under `artifacts/apple-container/run.*`; `run.log` is captured automatically.
Commands requiring `.git`, including the full CI wrapper, need a different setup.

Defaults are four CPUs and 6 GiB memory. Override
`RULES_MSBUILD_CONTAINER_CPUS` and `RULES_MSBUILD_CONTAINER_MEMORY` for a particular
experiment. `RULES_MSBUILD_CONTAINER_ARCH=amd64` is an available runner option,
not a claim that ARM64 results qualify x86-64.

The runtime native-build fixture needs additional namespace/capability setup;
follow [runtime native qualification (historical)](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/runtime-native.md) rather than assuming
this basic runner covers it. See [platform scope](platform-validation-scope.md).
The [old container runbook (historical)](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/historical-apple-container-runbook.md) is retained only
for reproducing retired discovery/replay experiments.
