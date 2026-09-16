# Pinned local MVP candidate qualification (#64)

Historical prerequisite qualification. The subsequent [MVP release sign-off](local-mvp-signoff.md)
records the merged implementation and current release measurements.

## Result and applicability

The single combination in the [support contract](local-mvp-contract.md) passes
local qualification: **99 correctness cases**, 20 paired preparation samples and
40 ordinary-MSBuild/adapter Build/Test samples. The unchanged preparation budget
passes; [performance findings](local-mvp-performance-findings.md) retain the
adapter's end-to-end overhead and bounded scope. This is candidate qualification;
release version/artifact selection and sign-off remain #65.

Production optimization and the main native matrix used
`85773b09f8bd915dc429f1b817d0f303c9d80010`. Final package controls, 58 preparation
unit tests, fallback and both timing harnesses used
`efb4baf3c367390ecde8679f4894192a86e54f95`. Between those revisions only
`tests/preparation_reuse/probe_mvp_package_inputs.py` and its unit regression
changed. Production tools, Bazel rules, pins and budget are byte-identical. The
later documentation/evidence commit adds no executable changes. Earlier checks
are therefore applicable to the measured candidate; they are not relabeled as
reruns at the later revision.

RUL-6 revision `c5934ce8e54dac12bdfc49996c3043303a50cdc2` is an ancestor of the
candidate. Its unchanged eligibility and lease/publication implementation passes
the same native correctness matrix under the optimized identity traversal.

## Acquisition

A new detached checkout under `/private/tmp`, empty owned HOME, fresh NuGet cache
and new output/cache directories were used. Entering `nix develop` from a minimal
`env -i` environment acquired the locked development environment; the documented
`python3 scripts/setup-starlark.py` acquired pinned validation tools. Four owned
.NET tools were built before correctness probes. All runs used short,
unsynchronized local paths to satisfy the qualified macOS path boundary.

The existing system Nix daemon/store was shared. This is clean user-state
acquisition on the supported host, not a fresh OS or an empty-store download
benchmark. The old-cache upgrade control deliberately imports earlier state and
is listed separately below.

| Component | Qualified identity |
| --- | --- |
| Host | macOS 27.0 (26A428), ARM64 |
| .NET SDK / runtime | Nix SDK 10.0.400 / 10.0.11 |
| MSBuild | 18.9.6.38015 |
| Bazel | Nixpkgs 8.4.2-(@non-git) |
| Python | 3.13.9 |
| Serilog | `49b5339ce85385dc52d4d8e8f2b8308becf23506` |

Serilog was independently cloned at the pin and restored into the empty owned
package cache. Its Git archive SHA-256 is
`bc289bfa238dd5c3f244027feade1b5cf9b0ae72ad33a3763f44583734bd4e98`.
The acquisition receipt records all 24 package archive hashes (including the
explicit PolySharp 1.16.0 upgrade control), 19 Nix closure paths and NAR hashes,
SDK/engine output, OS build, authored small-fixture hashes and acquisition mode.
The [evidence index](local-mvp-release-evidence.json) embeds that receipt and the
flake lock hash. Restore is explicit acquisition; measured native actions retain
network denial and do not invoke ambient restore.

## Correctness gates

| Probe | Passing cases | Raw report path in evidence archive |
| --- | ---: | --- |
| Reuse, corruption, publication, concurrency and small recovery | 17 | `reuse-recovery/report.json` |
| Source/import/reference/configuration consumers | 8 | `consumer-invalidation/report.json` |
| Discovery eligibility and identity | 27 | `discovery-contract/report.json` |
| Pinned Serilog discovery | 15 | `serilog-discovery/report.json` |
| Serilog producer-free fresh execution | 2 | `serilog-recovery/report.json` |
| Package/restore rejection and recovery | 9 | `package-inputs/report.json` |
| Fresh fallback | 2 | `fresh-fallback/report.json` |
| Actual approval tests, failure controls and relocation | 5 | `approval-tests/report.json` |
| Serilog library source/resource/signing/import/generator/recovery | 9 | `serilog-library/report.json` |
| Old-controller generation invalidation and actual execution | 1 | `old-controller-upgrade/report.json` |
| Legacy Clean/Rebuild/Pack/Publish rejection | 4 | `lifecycle-rejection/report.json` |

The first eight rows rerun the complete 85-case #6 matrix. Exact expected work
sets, diagnostics and consumer output are asserted, not inferred from cache
certificates. The nine library cases compare ordinary MSBuild and native adapter
behavior, including real generator-version changes. All 40 Build/Test samples
execute exactly one
`ApiApprovalTests.PublicApi_Should_Not_Change_Unintentionally` test; separate
negative controls require the expected approval mismatch and exception failure.
Recovered Bazel Build/Test obtains both project bundles from local disk cache
at a new location after producer removal, then forces the actual test. Other
recovery cases require fresh native project actions with an empty cache.

The old-controller control reads an actual pre-optimization generation, requires
`request-changed` and fresh preparation, executes exactly two native project
actions, and checks App output `mvp-calibration`. Generated tool inputs also
changed during rebuild; this does not isolate the controller as the only changed
input. A separate direct algorithm comparison proves identical snapshot records
and keys across 22 identical roots. Current-schema corruption, incompatible
requests and interrupted state are covered by the preparation tests and native
reuse controls. Persisted schemas did not change; complete controller/tool
identity invalidation remains the upgrade policy.

Legacy `tools/adapter.py` rejects Clean, Rebuild, Pack and Publish with
`unsupported operation`, nonzero exit and no output. Supported graph preparation,
export, Build and explicit Test are exercised by the probes. Lifecycle support
remains bounded by the frozen contract; broader #22/#26 behavior is deferred.

## Other checks

- `bash scripts/check.sh`: environment checks and nine tracked Starlark files pass.
- `bash scripts/check-dotnet.sh`: owned builds/style pass, including five policy tests.
- `bash scripts/dotnet.sh run --project tests/ActionRunner.Tests -c Release`: passes.
- Preparation suite: 58 tests pass after the final probe fixes.
- Graph/schema suite: 21 tests pass; tool-output suite: two tests pass.
- Starlark core: nine Python tests pass, including ten core and ten extension
  Bazel analysis tests. All four repository tests pass on retry; all five
  generated-extension tests pass.
- Final paired preparation: 20 measured samples pass, with setup and warm-up
  separate. End-to-end comparison: all 40 samples pass expected work/test oracles.
- `git diff --check`: passes. No GitHub CI was requested or dispatched.

## Retained unsuccessful attempts

No failed attempt counts toward the passing totals:

1. Initial environment check found missing Buildifier. Running the documented
   pinned setup command resolved it; the original failure log is retained.
2. Two repository tests hit an HTTP 500 downloading Bazel's protobuf archive from
   GitHub. All four tests passed after the service recovered. No dependency pin
   or repository rule changed.
3. Cold package controls exposed three probe assumptions hidden by warm fixtures.
   A rejected fresh request can create `obj` directories, deleting/recreating an
   analyzer can lose its mode bits, and fresh paths can rebuild owned tool inputs.
   The probe now restores generated namespace membership and file modes, checks
   the exact restored source hash, and compares tool fingerprints. If tools
   changed, recovery must miss with `request-changed`; the following unchanged
   request must reuse. The final run starts from a newly extracted, restore-only
   Serilog fixture and passes all nine cases. A unit regression covers directory
   and permission restoration. Adapter integrity checks were not relaxed.
4. An exploratory containment-only optimization exceeded the Serilog ratio budget.
   Its report is retained separately from final qualification; no threshold changed.

## Reproduction and retained evidence

Use a new checkout of the measured candidate and the pinned Nix shell. Set a new
owned HOME, NuGet cache and short TMPDIR; run the documented Starlark setup and
build GraphExport, EvaluationProbe, ReplayPlugin and ActionRunner. Restore the
pinned Serilog approval project for Release/net10.0 into that package cache and
acquire PolySharp 1.16.0 for its explicit upgrade control. The small fixture is
App → Shared with `Value.Text = "mvp-calibration"`; exact authored content and
entry request recipes are retained in the acquisition scripts and receipt.

Run the [#6 reproduction commands](local-mvp-correctness-findings.md#reproduction-and-evidence)
and the checks above. Add the library and performance gates:

```sh
python3 tools/probe_serilog_adapter.py --source <pinned-serilog-checkout> \
  --package-cache <package-cache> --output /private/tmp/qlib
python3 -m unittest discover -s tests/graph_execution -p test_prepare_graph.py -q
python3 -m unittest discover -s tests/msbuild_tools -q
python3 -m unittest discover -s tests/starlark -q
python3 -m unittest discover -s tests/starlark_extensions -q
```

The [performance commands](local-mvp-performance-findings.md#reproduction-and-limitations)
produce paired preparation, 40-sample Build/Test and frozen-budget reports. Run
probes serially: do not mutate controller/tool trees during identity or timing
checks. Each output directory must be new.

`evidence.zip` retains exact reports, native execution logs, traces, test results,
acquisition/check logs, failed attempts, exploratory profiles and the actual
invocation scripts. `evidence-manifest.json` hashes every retained file; the ZIP
has a separate SHA-256. Generated source/tool/cache payloads are excluded. The
committed evidence index retains portable case summaries, individual timing
samples, work oracles, input identities and raw-report hashes. Initial #5/#6
and PR-review evidence remain unchanged and separately labeled.

## Remaining scope

Qualification covers this single native macOS/Nix combination and narrow
Release/net10.0 Build/Test slice. System Nix store and filesystem caches are
shared, interactive host load is uncontrolled, aggregate memory is unmeasured,
and Bazel analysis/execution trace events overlap. No broader scale, Linux,
remote cache/execution, arbitrary NuGet or synchronized-storage claim follows.
Broad #8/#9/#49/#50/#58 remain open. #65 owns release packaging and sign-off.
