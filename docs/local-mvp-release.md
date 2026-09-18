# Local Build/Test MVP: v0.1.0-mvp.1

This is the historical v0.1.0-mvp.1 qualification guide. For the current Python-free
production commands, use [the native workflow guide](native-workflow.md). The
Python commands below reproduce the release experiments and their recorded evidence.

This experimental source release covers **native macOS ARM64, the default locked
Nix toolchain, and pinned Serilog Release/net10.0 Build/Test**. It retains normal
MSBuild compilation, SDK behavior, signing and package generators while Bazel
schedules project actions and supplies local disk-cache recovery.

The [support contract](local-mvp-contract.md) defines the exact boundary.
This is an early local adoption slice, not a general .NET build replacement.
The [release findings](local-mvp-signoff.md) record qualification, timings,
known failures, evidence applicability and the release checklist.

## Install and exercise Build/Test

Use an Apple silicon Mac with Nix installed and Git available. Choose a short,
unsynchronized local directory; do not use a File Provider-managed checkout.
The SDK, runtime, Python and Bazel come from `flake.lock`. Initial acquisition
requires network access and an existing working system Nix daemon/store.

```sh
git clone --branch v0.1.0-mvp.1 https://github.com/keegan-caruso/msbuild-bazel.git /private/tmp/rm
cd /private/tmp/rm
nix --extra-experimental-features 'nix-command flakes' develop
bash scripts/tooling.sh setup-starlark
bash scripts/check.sh
for tool in GraphExport EvaluationProbe ReplayPlugin ActionRunner; do
  bash scripts/dotnet.sh build "tools/$tool" -c Release --nologo
done
```

Inside that shell, acquire the exact upstream source and packages, then run the
Build/Test acceptance workflow. All output directories below must be new:

```sh
mkdir -p /private/tmp/rd/tmp
export TMPDIR=/private/tmp/rd/tmp
export DOTNET_CLI_HOME=/private/tmp/rd/cli
export NUGET_HTTP_CACHE_PATH=/private/tmp/rd/http
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_NOLOGO=1
git clone https://github.com/serilog/serilog.git /private/tmp/rd/upstream
git -C /private/tmp/rd/upstream checkout --detach 49b5339ce85385dc52d4d8e8f2b8308becf23506
bash scripts/dotnet.sh restore /private/tmp/rd/upstream/test/Serilog.ApprovalTests/Serilog.ApprovalTests.csproj \
  -p:Configuration=Release -p:TargetFramework=net10.0 --packages /private/tmp/rd/packages
python3 tools/probe_serilog_test_adapter.py --source /private/tmp/rd/upstream \
  --packages /private/tmp/rd/packages --output /private/tmp/rd/t
```

The final `report.json` must have `accepted: true`. This workflow builds the two
projects, executes exactly one unchanged upstream approval test, checks intended
failure controls, deletes the producer, recovers cached build bundles at a new
path, and forces the actual test again. Negative-control failures inside this
accepted report are intentional. Logs and TRX results are retained in the output.
The [explicit graph interface](graph-export-contract.md) and
[test declaration harness](../tools/probe_serilog_test_adapter.py) show the
supported export, materialize, build and test calls for integration.

### Reusable library Build

Use a separate restored library checkout and an explicitly owned package root.
Do not share source, state and generated-consumer directories.

```sh
git clone https://github.com/serilog/serilog.git /private/tmp/rd/library
git -C /private/tmp/rd/library checkout --detach 49b5339ce85385dc52d4d8e8f2b8308becf23506
mkdir -p /private/tmp/rd/library/.nuget/packages
bash scripts/dotnet.sh restore /private/tmp/rd/library/src/Serilog/Serilog.csproj \
  -p:Configuration=Release -p:TargetFramework=net10.0 \
  --packages /private/tmp/rd/library/.nuget/packages
cat > /private/tmp/rd/entries.json <<'JSON'
[{"project":"src/Serilog/Serilog.csproj","globalProperties":{"Configuration":"Release","TargetFramework":"net10.0"}}]
JSON
python3 tools/preparation_reuse.py --workspace /private/tmp/rd/library \
  --state /private/tmp/rd/state --output /private/tmp/rd/consumer1 \
  --entries /private/tmp/rd/entries.json -- \
  "$RULES_MSBUILD_BAZEL" --batch --nohome_rc --noworkspace_rc \
  --output_base=/private/tmp/rd/base build //:all \
  --disk_cache=/private/tmp/rd/disk --spawn_strategy=darwin-sandbox \
  --strategy=MsbuildProject=darwin-sandbox
```

Repeat with a new consumer path (`consumer2`) and the same state/cache to exercise
unchanged preparation reuse. Consumption runs inside the validation lease; a
saved certificate alone never authorizes reuse. Keep scratch paths short: macOS
action scratch paths over 208 UTF-8 bytes are rejected with a diagnostic.

## Defaults and experimental options

The default verifies complete mutable inputs and the declared Nix roots on every
preparation. Build-only preparation reuse is explicit through
`preparation_reuse.py`; explicit Test preparation remains fresh.

- `--trust-system-nix-store` explicitly trusts root-owned, non-writable, protected
  system Nix paths for the lifetime of the process. First use verifies contents.
  It assumes privileged Nix administration and storage integrity during that
  session. Restart after administrative changes or repair. A one-shot CLI does
  not retain the persistent Python session's larger savings.
- `--incremental-sources` permits guarded content-only C# refresh. Namespace,
  imports, metadata, packages, tools or ineligible resource changes retain fresh
  discovery. It does not bypass compilation or materialization.
- Both remain optional. Their [separate measurements](incremental-preparation-findings.md)
  do not represent the default Build/Test timing or broaden the support contract.
- Mutable checkout validation always reads content. Watcher events cannot replace
  it: the retained macOS mmap counterexample demonstrates a missed change.

## Artifacts and cache compatibility

The release contains source, documentation and reproduction scripts. Toolchain
and NuGet payloads are acquired separately from their pinned sources. The
release assets provide a source tarball, qualification evidence ZIP, provenance
JSON and SHA-256 checksums. `MODULE.bazel` retains the experimental `0.0.0` module
identity; this source release is not a Bazel Central Registry publication.

Graph export/request and generated graph use schema version 1 and graph contract
version 1. Discovery certificates use schema version 1; preparation manifests use
policy `leased-preparation-v1`, rather than a promised stable cross-release ABI.
Package manifests use schema version 1. Native runtime closure manifests use
schema version 2 (version 1 must be regenerated).
See [graph contracts](graph-export-contract.md), [package interface](bazel-interface.md)
and [preparation behavior](preparation-reuse-findings.md).

Reuse requires matching request, controller/tool bytes, SDK/Python identity,
source/package contents, host and discovery state. An upgrade can invalidate
preparation even when schema numbers stay unchanged. Regenerate preparation on
mismatch; do not edit a receipt or copy an old certificate to force acceptance.
Local disk-cache recovery is qualified on the same supported host. Cross-host,
remote-cache and cross-platform reuse are not granted by this release.

## Reproduce release qualification

From a Git checkout at this tag, in the default Nix shell:

```sh
bash scripts/qualify-local-mvp.sh /private/tmp/rq
```

Use a new short output directory and run serially without other builds. The
script obtains fresh source/packages, builds the owned tools, checks rule and
code-style gates, runs invalidation/recovery controls, measures five fresh/reuse
pairs per preparation workload and 40 Build/Test samples, then evaluates the
unchanged numeric budget. It stops at the first failed step and retains its log;
do not count an incomplete run as passing. Existing system Nix and ambient OS
caches remain shared. Interactive desktop load is uncontrolled.

The release evidence additionally records the prior-controller upgrade control,
backlog audit, delivered-source smoke check, exact commands and every retained
file's hash. Those release-specific checks are documented in the sign-off.
