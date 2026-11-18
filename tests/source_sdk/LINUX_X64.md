# Native Linux x64 source SDK recipe

This recipe prepares the coarse SDK 10.0.100 source action on Ubuntu 26.04 x64,
with Clang 18.1.8. It preserves the ARM64 defaults. A successful acquisition or
emulated tool probe does not qualify a native SDK build, cache recovery, component
scheduling, signing, or upstream test parity. The component graph/replay helpers
remain ARM64-only. The source revision and archive identity remain in `pin.json`;
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
inputs. No VMR source patch or full SDK build is involved.
From that VMR run `./prep-source-build.sh --no-bootstrap --bootstrap-rid linux-x64`. This is
input acquisition, rather than successful source-build evidence.

Assemble the separate SDK native package closure on Ubuntu 26.04 x64. Prerequisites
are Python, `dpkg-deb`, a host C compiler for Bazel's Python launchers, the pinned
SDK/Bazel bootstrap tools, download access and a case-sensitive output filesystem.
Docker is not required. The sealed probe requires nested namespaces and a permitted
Bubblewrap launcher; `--system-bwrap` verifies the packaged launcher against the
declared bytes without changing host policy.

```sh
bash scripts/setup.sh --toolchain-only
python3 scripts/assemble-native-toolchain.py /build/fresh-native \
  --architecture=x64 --sdk --probe --system-bwrap
```

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

Run the generated `//:smoke` with the repository Bazel wrapper or explicit pinned
Bazel executable, conservative resource limits and the shared bounded cache. Its
source action builds the VMR offline inside the read-only declared native root;
its produced SDK then compiles and executes the net10 smoke app. Preserve the
source action archive hash, acquisition report, build log/time, actual smoke test
output and execution log. Native x64 qualification remains pending until those
steps actually pass; stopped-producer read-only recovery is a separate check.

The connected bootstrap step additionally needs outbound access to the pinned
Microsoft archive URLs and the public NuGet feeds selected by the VMR. Record its
Restore assets/logs and generated Bootstrap archive digest. A producer qualification
run needs sufficient disk space for the native root, VMR, bootstrap and full source
build (the bounded job checks 100 GiB available), plus time to build the complete
upstream SDK. Successful input assembly and emulated probes do not replace that
native execution result.
