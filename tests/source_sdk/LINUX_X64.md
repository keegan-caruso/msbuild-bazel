# Native Linux x64 source SDK recipe

Prepares the coarse SDK 10.0.100 source action on Ubuntu 26.04 x64 (Clang 18.1.8, Bazel 9.3.2). Native smoke-first production and local package/Razor/Publish consumers pass ([pins, archive identities, and limits](../../docs/support.md#native-ubuntu-2604-x64-sdk)). Preserves ARM64 defaults; component graph/replay helpers remain ARM64-only. Source revision/archive identity live in `pin.json` (`qualifiedSdkBundle`/`qualificationImage` there are historical ARM64). Acquisition/emulated probes alone do not establish production, recovery, or upstream test parity.

Acquire bootstrap inputs on any download-capable machine (`acquire_x64.py` verifies exact sizes and SHA256s in [pin-linux-x64.json](pin-linux-x64.json) for all three archives and never overwrites a mismatched file):

```sh
python3 tests/source_sdk/acquire_x64.py /path/to/fresh-acquisition
python3 tests/source_sdk/acquire_x64.py /path/to/fresh-acquisition --verify
```

The 1.4 GB previously source-built archive is the upstream `centos.10-x64` bootstrap input (not an Ubuntu 26 product). Upstream preparation replaces portable packages for `linux-x64` via connected NuGet Restore to produce `Private.SourceBuilt.Artifacts.Bootstrap.tar.gz`. Preserve its logs, generated archive hash (recorded by `source_action_prepare.py`; distinct from the raw archive hash), and resolved package inventory before the offline Bazel action.

From a fresh extracted VMR matching `pin.json` SHA256, inside the native SDK tool boundary, run an independent baseline (full upstream source build):

```sh
RULES_MSBUILD_SOURCE_SDK_ARCH=x64 bash tests/source_sdk/baseline.sh \
  /path/to/fresh-vmr /path/to/fresh-baseline-evidence /path/to/fresh-acquisition
```

Or run connected preparation only: verify acquisition, extract bootstrap SDK into `VMR/.dotnet`, copy the raw previously source-built archive into `VMR/prereqs/packages/archive/` (keeping original filename), and generate the portable bootstrap:

```sh
python3 tests/source_sdk/prepare_x64_bootstrap.py /path/to/fresh-vmr
```

Runs the unchanged VMR bootstrap project via `dotnet restore` matching upstream `BootstrapArtifacts` (which upstream skips when the raw archive exists), verifies the raw pin before replacement, and writes generated digest/members to `VMR/artifacts/log/bootstrap-inputs.json`. Preserve that report and `prep-bootstrap.log` (restored feed packages are connected inputs). Does not patch the VMR or build the SDK (producer keeps the [IdentityModel version patch](patches/identitymodel-file-version.patch)). Then run `./prep-source-build.sh --no-bootstrap --bootstrap-rid linux-x64` (acquisition only, not build evidence).

Assemble the Ubuntu 26.04 x64 SDK native closure (requires Python, `dpkg-deb`, host GCC/G++ for Bazel launchers, pinned SDK/Bazel tools, download access, case-sensitive filesystem, nested namespaces, and permitted Bubblewrap; no Docker needed; `--system-bwrap` verifies packaged launcher bytes without changing host policy):

```sh
bash scripts/setup.sh --toolchain-only
python3 scripts/assemble-native-toolchain.py /build/fresh-native \
  --architecture=x64 --sdk --probe --system-bwrap
```

The SDK root declares only root (UID/GID 0) and `builder` (UID/GID 1000, home `/tmp`); no host account files enter the archive. Sealed probe and x64 script fail before Restore if caller UID/primary GID cannot resolve while preserving namespace mapping (qualification uses UID/GID 1000; other UIDs unqualified). Outputs `native.tar`, `bwrap`, and `receipt.json`—use exact report hashes, never host `/usr`. The [overlay recipe](native_overlay/README.md) provides an independent OCI/preflight control and supplemental package pins. Assembly includes dependencies, LLVM 18 aliases, merged-usr aliases, timezone, and x64 `/lib64` loader. Keep manifest, archive hash, and probe log.

Create the offline Bazel source producer:

```sh
python3 tests/source_sdk/source_action_prepare.py SOURCE_ARCHIVE PREPARED_VMR FRESH_ACTION \
  --architecture=x64 --native-tools=NATIVE_TAR --native-tools-sha256=NATIVE_SHA256 \
  --sandbox=BWRAP --sandbox-sha256=BWRAP_SHA256 --system-bwrap
```

Verifies tool/Bubblewrap archives and bootstrap ELF arch, selects pinned SDK 10.0.400 x64 driver, and generates x64 constraints and `linux-x64` SDK registration. `--system-bwrap` opts into verified `/usr/bin/bwrap` for Ubuntu AppArmor (declared executable remains a checked input; no policy change/fallback; omit where declared executable is permitted).

Start directly with `//:smoke` (SDK layout consumes the producer in execution config; prebuilding `:sdk` or `:evidence` uses a different config and compiles twice). Give `//:smoke` the full deadline, then keep identical startup options, workspace, output base, and action options for consumers:

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

Builds the VMR offline in the read-only root and runs the `net10` smoke app with fresh roots and external caches disabled. Require exactly one `SourceSdkBuild` in the execution log; both SDK archive and `result.tar` come from that action under `bazel-out/*/bin/sdk.generated/` (including exec config; do not build another target for evidence).

Run consumers requiring source reuse:

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

Reports distro RID `ubuntu.26.04-x64`, SDK `10.0.100`, Core/ASP.NET `10.0.0`, registered as `linux-x64` (older distros unqualified). Preserve archive hash, acquisition report, build log/time, smoke output, and execution log. Passed at rules revision `de47cfe1df06e6ec82d14aff56425af6e6227b93` (one real source action, zero extra source builds in consumers; separate exact-archive handoff also passed). For stopped-producer read-only recovery on the same x64 host, see the [SDK qualification](../../docs/support.md#native-ubuntu-2604-x64-sdk).

Connected bootstrap needs outbound access to pinned Microsoft archive URLs and VMR NuGet feeds (record Restore assets/logs and Bootstrap archive digest). Producer qualification requires ≥ 70 GiB free disk for native root, VMR, bootstrap, and build, plus full build time; input assembly/emulated probes do not substitute for native execution.
