# Local MVP invalidation and recovered execution (issue #6 / RUL-8)

## Candidate and scope

Native macOS ARM64 27.0 (26A428), the locked Nix SDK 10.0.400/runtime
10.0.11 and Nixpkgs Bazel 8.4.2 from the [support contract](local-mvp-contract.md).
The candidate is base `498114a4b67ba56682b93fb6a6f98d82d1b2acaf` plus
this change, including the macOS action-path guard. The retained evidence
manifest binds the final commit, patch, flake lock and individual report hashes.
Runs are serial on unsynchronized local storage with short output bases.

All **85 native correctness cases passed**. Expected and observed work sets
match. The [evidence index](local-mvp-evidence.json) retains named case results,
individual calibration samples, phase summaries, code-input hashes and raw
report hashes. No performance qualification is implied.

| Probe | Cases passed | Report in evidence bundle |
| --- | ---: | --- |
| Package/restore consumer controls | 9 | `package-inputs/report.json` |
| Reuse, publication, concurrency and small recovery | 17 | `reuse-recovery/report.json` |
| Source/import/reference/configuration consumer controls | 8 | `consumer-invalidation/report.json` |
| Serilog producer-free recovery | 2 | `serilog-recovery/report.json` |
| Fresh fallback eligibility | 2 | `fresh-fallback/report.json` |
| Discovery boundary and identity | 27 | `discovery-contract/report.json` |
| Pinned Serilog discovery | 15 | `serilog-discovery/report.json` |
| Approval execution, failure controls and relocation | 5 | `approval-tests/report.json` |

All 45 preparation unit tests, owned .NET build/style checks (including five
policy-enforcement tests), ActionRunner tests and repository/Starlark checks
also passed. No GitHub CI was dispatched.

## Consumer work sets

`tests/preparation_reuse/probe_mvp_invalidation.py` prepares each selected input
state, builds with native sandbox actions and executes the resulting App.
It checks the exact list of projects that execute, not just an invalidated
certificate. A shared local disk cache permits previously built input states
to recover their original outputs.

| Change | Preparation | Expected executed projects | Expected App output |
| --- | --- | --- | --- |
| Cold | Fresh | App, Shared | `mvp:base` |
| Unchanged | Reuse | None | `mvp:base` |
| Add App source | Fresh | App | `mvp:added` |
| Remove added source | Fresh | None; prior input state is cached | `mvp:base` |
| Add optional import defining OPTIONAL | Fresh | App, Shared | `mvp:base` then `optional` |
| Remove optional import | Fresh | None; prior input state is cached | `mvp:base` |
| Authored reference metadata | Fresh fallback, empty disk cache | App, Shared | `mvp:base` |
| Request Debug | Reject unsupported configuration | No consumer | Actionable configuration diagnostic |

The reference's authored `AdditionalProperties=Configuration=Release` is
outside reusable XML eligibility. Fresh export preserves the edge and the
supported Release configuration. Debug cannot receive a stale Release plan;
its rejection preserves the committed cache pointer.

## Restore and packages

`tests/preparation_reuse/probe_mvp_package_inputs.py` selects the pinned Serilog
library. Cold preparation discovers once; unchanged preparation reuses.
Adding valid whitespace to the restored assets JSON refreshes preparation and
executes exactly one fresh native Serilog action with an empty disk cache.

Malformed assets JSON, a corrupted or missing PolySharp analyzer assembly and
a changed PolySharp import are rejected. Each control verifies that no consumer
is published and the committed generation remains unchanged. Restoring exact
source content permits reuse followed by one fresh native Serilog action in an
independent empty disk cache; a further unchanged request reuses again.

The first two probe attempts exposed a harness isolation problem: fresh fallback
can rewrite generated `obj` assets caches while rejecting bad inputs. The final
probe saves and restores those generated files around each negative control and
asserts the complete source content hash is unchanged. The failed attempts are
retained and excluded from passing results. No production integrity check was
relaxed to obtain the final result.

## Publication, invalidation and recovery controls

- The original reuse probe checks cold/unchanged/timestamp-only/source-edited
  work flags, missing/corrupt payload, manifest and pointer handling, interrupted
  staging and pointer replacement, concurrent consumers and runner changes.
  Corrupt state is rejected as reuse authority; valid source is freshly prepared.
  Interrupted publication retains the prior committed generation.
- Two consumer processes serialize under the retained lease. Both receive valid
  results; a consumer exception is not retried as a fresh user command.
- Small-graph recovery deletes the producer and executes two fresh native
  project actions, then runs the recovered App with the expected output.
- Serilog recovery deletes the producer and relocated source before executing
  one fresh native library action. A separately compiled consumer loads the
  recovered assembly and prints `Serilog`.
- Discovery controls cover nested and wildcard imports, optional-file absence,
  source membership, restore wrappers, referenced projects, timestamp-only
  changes and unqualified XML. Native read/write/network denial and ordinary
  exporter parity are checked independently. These discovery cases complement
  the actual consumer work sets above; certificate checks alone do not prove
  executable output behavior.
- Explicit test requests and unsupported authored XML take fresh preparation
  and do not publish a reusable generation. The approval-test harness checks
  execution and negative controls independently of build-only reuse.

The 40-sample [Build/Test calibration](local-mvp-calibration-findings.md)
also forces exactly one approval Fact per sample. Its recovered Bazel cases
obtain both build bundles from disk cache and execute the test under the native
sandbox after producer removal. This complements empty-cache fresh execution;
a cache hit is not counted as a fresh project action.

## Reproduction and evidence

Enter the locked default Nix shell, prebuild the four tools and acquire the
pinned source/package inputs as described in the support contract. Use new,
short output directories for each command; the probes refuse an existing root.

```sh
python3 tools/probe_preparation_reuse.py --output /private/tmp/mr2
python3 tests/preparation_reuse/probe_mvp_invalidation.py --output /private/tmp/mi2
python3 tests/preparation_reuse/probe_mvp_package_inputs.py \
  --source <restored-serilog-library> --output /private/tmp/mp3
python3 tests/preparation_reuse/probe_serilog_reuse.py \
  --source <pinned-git-source> --packages <package-cache> --output /private/tmp/msr1
python3 tests/preparation_reuse/probe_fresh_fallback.py \
  --workspace <restored-small-fixture> --output /private/tmp/mf1
python3 tools/probe_discovery_contract.py --output /private/tmp/md1
python3 tools/probe_serilog_discovery.py \
  --source <pinned-git-source> --packages <package-cache> --output /private/tmp/msd1
python3 tools/probe_serilog_test_adapter.py \
  --source <pinned-git-source> --packages <package-cache> --output /private/tmp/mt1
python3 -m unittest discover -s tests/preparation_reuse -q
bash scripts/check.sh
bash scripts/check-dotnet.sh
bash scripts/dotnet.sh run --project tests/ActionRunner.Tests -c Release
```

Each probe writes `report.json` with named cases, work flags and diagnostics.
Native execution logs, test result files and detailed process logs are retained
in the evidence bundle. The manifest excludes generated cache/tool/source
payloads but preserves report bytes and hashes. Existing historical acceptance
is linked from the contract; this report does not claim Linux, remote execution,
other SDK distributions, synchronized storage or arbitrary package support.

The ratio performance gate remains #7. Clean acquisition and final candidate
release qualification remain #64, and packaging/sign-off remain #65.
