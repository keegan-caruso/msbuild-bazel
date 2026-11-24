# Build the .NET 11 VMR on Linux ARM64

Targets SDK **11.0.100** with `Microsoft.NETCore.App` and `Microsoft.AspNetCore.App` **11.0.0** (VMR commit `297acf930fb0f5c07fd4e51d78e521b4ad2e5d1f`, build ID `20261029.18`). Use the build-produced source archive from the [upstream release](https://github.com/dotnet/dotnet/releases/tag/v11.0.100) (release signature covers its ownership metadata).

## Prepare the bootstrap on Linux ARM64

In an empty directory with Bash, `curl`, GnuPG, GNU `tar`, `sha256sum`, and network access (keep original downloads; bootstrap replaces its working copy of the raw package archive):

```bash
set -euo pipefail
release=https://github.com/dotnet/dotnet/releases/download/v11.0.100
feed=https://builds.dotnet.microsoft.com/dotnet
rc=11.0.100-rc.2.26504.105
raw=Private.SourceBuilt.Artifacts.$rc.centos.10-x64.tar.gz
curl -fLsS "$feed/source-build/dotnet-source-11.0.100-rtm.26529.118.tar.gz" -o source.tar.gz
curl -fLsS "$release/dotnet-11.0.100.tar.gz.sig" -o source.sig
curl -fLsS https://dot.net/release-key-2023 | gpg --dearmor > release-key.gpg
gpgv --keyring "$PWD/release-key.gpg" source.sig source.tar.gz
curl -fLsS "$feed/Sdk/$rc/dotnet-sdk-$rc-linux-arm64.tar.gz" -o sdk-bootstrap.tar.gz
curl -fLsS "$feed/source-build/$raw" -o "$raw"
sha256sum -c <<HASHES
87df2a2d4b8931e50c88e4fb2b150092960135d649a57bfb41bec72085e9d38a  source.tar.gz
a63f77bda2335c85d4f9f76a57f9cc216d3d6bfc5277fc26a492c637bc502898  sdk-bootstrap.tar.gz
5bd1bbf2bf9ef75d24a816f976ebefcbf7a46c1dade359c3b0186f2d3993e527  $raw
HASHES
mkdir vmr
tar -xzf source.tar.gz --strip-components=1 -C vmr
mkdir -p vmr/.dotnet vmr/prereqs/packages/archive vmr/artifacts/{prep-bootstrap,log}
tar -xzf sdk-bootstrap.tar.gz -C vmr/.dotnet
cp "$raw" vmr/prereqs/packages/archive/
tar -xzf "$raw" -C vmr/artifacts/prep-bootstrap PackageVersions.props
(
  cd vmr
  cp eng/bootstrap/buildBootstrapPreviouslySB.csproj src/sdk/NuGet.config artifacts/prep-bootstrap/
  export DOTNET_ROOT="$PWD/.dotnet" DOTNET_CLI_HOME="$PWD/artifacts/cli-home"
  "$DOTNET_ROOT/dotnet" restore artifacts/prep-bootstrap/buildBootstrapPreviouslySB.csproj \
    /bl:artifacts/log/prep-bootstrap.binlog \
    -p:ArchiveDir="$PWD/prereqs/packages/archive/" -p:PortableTargetRid=linux-arm64
)
sha256sum vmr/prereqs/packages/archive/Private.SourceBuilt.Artifacts.Bootstrap.tar.gz
```

Signature verifies with key `A30E1CAFB4BBD279FEC7E47CFDBF53C24DB4872E`. Bootstrap consumes the CentOS x64 package collection and replaces target-specific packages via Linux ARM64 restore. Record the generated archive digest with the binlog. The RC SDK runs bootstrap and source build; product tests use the resulting 11.0.100 SDK.

## Run the Bazel producer

In the Linux ARM64 guest, set `rules` to the absolute checkout path and `native` to the qualified Ubuntu 26.04 / LLVM 18.1.8 native archive. Preparation verifies source digest, bootstrap host arch/version, portable package inventory, and native archive digest. Use a fresh workspace with room for extracted VMR and intermediates:

```bash
work=$(mktemp -d)
python3 "$rules/tests/source_sdk/source_action_prepare.py" \
  "$PWD/source.tar.gz" "$PWD/vmr" "$work/workspace" \
  --pin="$rules/tests/source_sdk/pin-linux-arm64-11.json" \
  --native-tools="$native" \
  --native-tools-sha256=1854d067717cba3afe85c01e166e2a2c7d95c4dafea89e172b69da8b536c874a
(
  cd "$work/workspace"
  bash "$rules/scripts/bazel-launcher.sh" --batch --output_base="$work/base" \
    --ignore_all_rc_files test //:smoke --jobs=1 --lockfile_mode=off \
    --test_output=all --execution_log_json_file="$work/producer.execution.json"
)
```

`//:smoke` consumes the SDK as a Bazel toolchain, builds a `net11.0` executable, and verifies its runtime version. The controller SDK compiles the Bazel driver; the VMR uses its pinned RC SDK to build the product toolchain.

## Run an app with the runtime alone

Copy the produced SDK archive to a second Linux ARM64 guest, verify its SHA-256 against the producer (`sdk_archive`), extract on a symlink-capable native Linux filesystem, and run from a fresh directory:

```bash
mkdir sdk
tar --no-same-owner -xzf "$sdk_archive" -C sdk
python3 "$rules/tests/source_sdk/vmr_runtime.py" --sdk="$PWD/sdk" \
  --vmr-revision=297acf930fb0f5c07fd4e51d78e521b4ad2e5d1f "$PWD/runtime-check"
```

Verifies SDK/shared-framework version stamps against the VMR revision, packages and re-extracts the host and both shared frameworks, builds a `net11.0` app with the source SDK, runs it with the extracted host, and writes CoreLib path, arch, and runtime version to `runtime-check/report.json`.

To test the standalone Core runtime tarball (`artifacts/assets/Release/Runtime/`), set `runtime_archive` and producer `runtime_sha256`:

```bash
python3 "$rules/tests/source_sdk/vmr_runtime.py" --sdk="$PWD/sdk" \
  --vmr-revision=297acf930fb0f5c07fd4e51d78e521b4ad2e5d1f \
  --runtime-archive="$runtime_archive" --runtime-sha256="$runtime_sha256" \
  --app="$PWD/runtime-check/app/out/app.dll" "$PWD/standalone-check"
```

## Recover the SDK and exercise consumers

For cache recovery, add `--remote_cache="$cache" --remote_upload_local_results=true --remote_cache_async=false --remote_download_outputs=all` to the producer test (`cache` = shared HTTP cache). With original workspace and output symlinks available:

```bash
export RULES_MSBUILD_BAZEL="$rules/scripts/bazel-launcher.sh"
python3 "$rules/tests/source_sdk/source_action_recovery.py" \
  "$work/workspace" "$work/recovery" --cache="$cache" --seed-output-base="$work/base"
python3 "$rules/tests/source_sdk/consumer_scenarios.py" "$work/scenarios" \
  --workspace="$work/recovery/workspace" --output-base="$work/recovery/base" \
  --batch --bazel-startup-option="--output_user_root=$work/recovery/user" \
  --require-source-reuse --bazel-option="--remote_cache=$cache" \
  --bazel-option=--remote_upload_local_results=false \
  --bazel-option=--remote_download_outputs=all
```

For a fresh consumer that only runs the app (producer stopped, actions cached), download only top-level outputs and force test execution (SDK archive and expanded layouts stay remote):

```bash
cd "$work/workspace"
bash "$rules/scripts/bazel-launcher.sh" --batch --output_base="$work/smoke-base" \
  --output_user_root="$work/smoke-user" --ignore_all_rc_files test //:smoke \
  --lockfile_mode=off --disk_cache= --remote_cache="$cache" \
  --remote_upload_local_results=false --remote_download_outputs=toplevel \
  --nocache_test_results --test_output=all
```

Verify this mode with the qualification driver (seed workspace and output symlinks available):

```bash
python3 "$rules/tests/source_sdk/source_action_recovery.py" \
  "$work/workspace" "$work/smoke-recovery" --cache="$cache" --smoke-only
```

`--smoke-only` checks the SDK digest in Bazel's execution log against the seed archive and verifies printed runtime version; use full recovery above to download and hash SDK bytes locally. Full recovery checks a fresh output base, exact SDK archive digest, and smoke execution after body/API edits; `consumer_scenarios.py` packs/consumes a NuGet package, renders Razor, publishes an app, and checks its runtime.

### Managed and NativeAOT compiler inputs

`produced_managed_registered` uses `:managed_layout` (omits NativeAOT runtime and ILCompiler packs; keeps all reference, managed runtime, and apphost packs). `:layout` and `:produced_files` keep all seven pack directories. Select the full toolchain for NativeAOT Publish:

```bash
bash "$rules/scripts/bazel-launcher.sh" build //:YOUR_NATIVE_AOT_GRAPH \
  --extra_toolchains=//:produced_registered
```

`YOUR_NATIVE_AOT_GRAPH` is an authored graph with `PublishAot=true` and declared native compiler inputs (not in the smoke fixture). Switching toolchains changes compiler inputs without rebuilding the SDK archive; extraction verifies the exact pinned pack inventory.
