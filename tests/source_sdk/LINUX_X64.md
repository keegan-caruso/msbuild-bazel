# Native Linux x64 source SDK recipe

This recipe prepares the coarse SDK 10.0.100 source action on Ubuntu 26.04 x64,
with Clang 18.1.8 and Bazel 9.3.2. Native smoke-first production and local
package/Razor/Publish consumers pass; [pins, archive identities and limits](../../docs/support.md#native-ubuntu-2604-x64-sdk)
record the qualification. It preserves the ARM64 defaults. Acquisition or emulated
probes alone do not establish production, recovery or upstream test parity. The
component graph/replay helpers remain ARM64-only. The source revision and archive identity remain in `pin.json`;
the historical `qualifiedSdkBundle` and `qualificationImage` there describe ARM64.

Acquire bootstrap inputs on any download-capable machine, before starting the
bounded native build. The helper verifies exact byte lengths and SHA256 hashes
in [pin-linux-x64.json](pin-linux-x64.json); all three archives were downloaded
and hashed. It never replaces an existing mismatched archive.

```sh
python3 tests/source_sdk/acquire_x64.py /path/to/fresh-acquisition
python3 tests/source_sdk/acquire_x64.py /path/to/fresh-acquisition --verify
```

The 1.4 GB previously source-built archive is the upstream `centos.10-x64`
bootstrap input, rather than a claimed Ubuntu26 product. Upstream preparation
replaces its portable packages for `linux-x64` and generates
`Private.SourceBuilt.Artifacts.Bootstrap.tar.gz` through NuGet Restore. That
Restore is a connected acquisition step. Preserve its logs, generated archive
hash and resolved package inventory before the offline Bazel action. The generated
archive hash is recorded by `source_action_prepare.py`; it is not interchangeable
with the raw archive hash in the acquisition pin.

Start from a fresh extracted VMR whose SHA256 matches `pin.json`. Run preparation
and baseline only inside the selected native SDK tool boundary. To obtain an
independent baseline, which performs the complete upstream source build:

```sh
RULES_MSBUILD_SOURCE_SDK_ARCH=x64 bash tests/source_sdk/baseline.sh \
  /path/to/fresh-vmr /path/to/fresh-baseline-evidence /path/to/fresh-acquisition
```

To run only connected preparation, verify acquisition, extract the pinned
bootstrap SDK into `VMR/.dotnet`, and copy the pinned previously source-built
archive into `VMR/prereqs/packages/archive/`, retaining its original filename.
With the raw archive staged, generate its portable bootstrap explicitly:

```sh
python3 tests/source_sdk/prepare_x64_bootstrap.py /path/to/fresh-vmr
```

This runs the pinned VMR's unchanged bootstrap project through `dotnet restore`,
with the same staging and properties as upstream `BootstrapArtifacts`. Upstream
preparation skips that step when its raw archive is already present. The helper
verifies the raw pin before the project replaces it and records the generated
archive digest and member identities in `VMR/artifacts/log/bootstrap-inputs.json`.
Preserve that report and `prep-bootstrap.log`; restored feed packages are connected
inputs. Bootstrap generation does not patch the VMR or run a full SDK build; the
later producer retains the [IdentityModel version patch](patches/identitymodel-file-version.patch).
From that VMR run `./prep-source-build.sh --no-bootstrap --bootstrap-rid linux-x64`. This is
input acquisition, rather than successful source-build evidence.

Assemble the separate SDK native package closure on Ubuntu 26.04 x64. Prerequisites
are Python, `dpkg-deb`, host GCC/G++ for Bazel's launchers, the pinned
SDK/Bazel bootstrap tools, download access and a case-sensitive output filesystem.
Docker is not required. The sealed probe requires nested namespaces and a permitted
Bubblewrap launcher; `--system-bwrap` verifies the packaged launcher against the
declared bytes without changing host policy.

```sh
bash scripts/setup.sh --toolchain-only
python3 scripts/assemble-native-toolchain.py /build/fresh-native \
  --architecture=x64 --sdk --probe --system-bwrap
```

The SDK root declares account records for root (UID/GID 0) and the ordinary
`builder` user (UID/GID 1000), with `/tmp` as the writable home. The sealed probe
and x64 source script fail before Restore if the invoking UID or primary GID
cannot be resolved in that root. They preserve the caller's namespace mapping;
other host UIDs are not qualified. Native x64 qualification uses UID/GID 1000.
No host account files enter the archive.

This produces `native.tar`, `bwrap`, and `receipt.json`. Use the report's exact hashes;
do not capture the native host's `/usr` as the x64 SDK toolchain. The
[overlay recipe](native_overlay/README.md) provides an independent OCI/preflight
control and exact supplemental package pins. The complete package assembly must
include its dependencies, LLVM18 aliases, merged-usr aliases, timezone and the
x64 `/lib64` loader path. Keep the root's manifest, archive hash and probe log.

After connected preparation, create the offline Bazel source producer:

```sh
python3 tests/source_sdk/source_action_prepare.py SOURCE_ARCHIVE PREPARED_VMR FRESH_ACTION \
  --architecture=x64 --native-tools=NATIVE_TAR --native-tools-sha256=NATIVE_SHA256 \
  --sandbox=BWRAP --sandbox-sha256=BWRAP_SHA256 --system-bwrap
```

The x64 path requires explicit verified tool and Bubblewrap archives, checks the
bootstrap host ELF architecture, selects the pinned SDK 10.0.400 x64 action
driver, and generates native x64 execution constraints and `linux-x64` produced
SDK registration. `--system-bwrap` opts into the shared driver's verified packaged
`/usr/bin/bwrap` launcher for Ubuntu AppArmor policy; the declared executable
remains an input and must match. There is no security-policy change or fallback.
Omit the option where the declared executable is already permitted.

Start directly with the generated `//:smoke` target. SDK layout consumes its
producer in the execution configuration; prebuilding top-level `:sdk` or
`:evidence` selects a different configuration and compiles the SDK again. Give
the first smoke command the full producer deadline, then retain the same startup
options, workspace, output base and action options for subsequent consumers:

```sh
rules_repo=/path/to/msbuild-bazel
cd /path/to/fresh-action
timeout --kill-after=30 7200 "$rules_repo/scripts/bazel-launcher.sh" \
  --batch --host_jvm_args=-Xmx1024m \
  --output_base=/build/fresh-sdk-base --output_user_root=/build/fresh-sdk-user \
  --ignore_all_rc_files test //:smoke --jobs=2 --local_test_jobs=1 \
  --lockfile_mode=off --disk_cache= --remote_cache= \
  --nocache_test_results --test_output=all \
  --execution_log_json_file=/build/fresh-sdk-smoke.execution.json
```

This correctness command uses fresh Bazel roots and disables external action
caches. It builds the VMR offline inside the declared read-only root, then
compiles and executes the net10 app with its produced SDK. Require exactly one
executed `SourceSdkBuild` in that execution log. Both its SDK archive and
`result.tar` are emitted by the same action; locate the single pair below
`bazel-out/*/bin/sdk.generated/`, including the execution-configuration directory.
Do not invoke another target to obtain the evidence archive.

The consumer driver accepts matching startup options and rejects new source
producer execution when reuse is required:

```sh
RULES_MSBUILD_BAZEL="$rules_repo/scripts/bazel-launcher.sh" \
  python3 "$rules_repo/tests/source_sdk/consumer_scenarios.py" /build/fresh-sdk-consumers \
  --workspace="$PWD" --output-base=/build/fresh-sdk-base --batch \
  --bazel-startup-option=--host_jvm_args=-Xmx1024m \
  --bazel-startup-option=--output_user_root=/build/fresh-sdk-user \
  --require-source-reuse --bazel-option=--local_test_jobs=1 \
  --bazel-option=--disk_cache= --bazel-option=--remote_cache= \
  --bazel-option=--nocache_test_results
```

The SDK reports distro RID `ubuntu.26.04-x64`, SDK `10.0.100` and Core/ASP.NET
runtimes `10.0.0`; its toolchain registration uses the base platform `linux-x64`.
This does not qualify execution on older distributions. Preserve the archive
hash, acquisition report, build log/time, actual smoke output and execution log.
This complete smoke-first sequence passed at rules revision
`de47cfe1df06e6ec82d14aff56425af6e6227b93`, with one real source action and no
additional source execution during the consumer scenarios. A separate exact-archive
handoff also passed. Stopped-producer read-only recovery remains unqualified for
x64; these runs make no speedup or byte-reproducibility claim.

The connected bootstrap step additionally needs outbound access to the pinned
Microsoft archive URLs and the public NuGet feeds selected by the VMR. Record its
Restore assets/logs and generated Bootstrap archive digest. A producer qualification
run needs sufficient disk space for the native root, VMR, bootstrap and full source
build (the bounded qualification job required at least 70 GiB available), plus
time to build the complete upstream SDK. Successful input assembly and emulated probes do not replace that
native execution result.
