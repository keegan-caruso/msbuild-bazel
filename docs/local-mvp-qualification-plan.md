# Local MVP calibration and correctness protocol

Tracks [#5](https://github.com/keegan-caruso/msbuild-bazel/issues/5) / RUL-7
and [#6](https://github.com/keegan-caruso/msbuild-bazel/issues/6) / RUL-8 under
the [candidate contract](local-mvp-contract.md). This is an execution protocol;
results are in the [calibration findings](local-mvp-calibration-findings.md),
[predeclared budget](local-mvp-preparation-budget.json) and
[correctness findings](local-mvp-correctness-findings.md).

## Environment preflight (2026-09-15)

The execution host reports macOS 27.0 (26A428), ARM64. Nix was initially
absent; the user installed Nix 2.35.2 and the locked environment now passes
the toolchain and Starlark checks. The qualification implementation requires the SDK at
`/nix/store/f3kvj2nc26gn7rh5mnfnaa2dgy2p10v3-dotnet-sdk-10.0.400/share/dotnet`
and calls `/nix/var/nix/profiles/default/bin/nix-store -qR` to bind its runtime
closure. This exact path was acquired successfully. SDK import paths and hashes are also allowlisted. A different SDK
installation cannot stand in for this environment without new qualification.

`python3 -m unittest discover -s tests/preparation_reuse -q` passed all 45
tests on this host. These are unit/contract tests with mocked host acquisition;
they do not establish native reuse, recovered execution or performance here.

## #5: calibration before performance qualification

1. Record candidate Git SHA and diff, flake lock hash, SDK/MSBuild/runtime
   versions, Nix store closure, Python identity, Bazel distribution, OS/build,
   architecture and power/load conditions. Do not time concurrently with tool
   acquisition, compilation in another task or correctness probes.
2. Acquire the pinned Serilog source and packages. Build all four adapter tools
   before the reuse experiment. Retain restore and tool-build costs separately.
3. Measure the selected Serilog library and small discovery fixture separately.
   Compare the existing fresh exporter/materializer path with unchanged eligible
   reuse. Include input sealing, full-tree hashing, payload verification and
   consumer copying in preparation wall time. Never report only work skipped.
4. Use five measured repetitions per workload/path after a separately reported
   warm-up. Alternate fresh/reuse order. Each consumer directory is new; keep
   the owned reuse/discovery root stable, record its seed cost separately, and
   assert each reuse sample reports `reused=true`, `discoveryExecuted=false`,
   `materializationExecuted=false`, `toolBuildsExecuted=false`.
5. Record each sample and median/min/max; include failures instead of silently
   replacing slow or failed samples. Hash source inputs before and after the
   sequence and verify resulting graph/output behavior. Fresh discovery may
   create MSBuild assets caches during warm-up; record both pre-warm-up and
   post-warm-up identities, then require unchanged inputs throughout measurement.
6. Run the existing Serilog ordinary-MSBuild/adapter phase comparison under the
   same toolchain. Its fresh, unchanged, source-edited and recovered cases
   provide preparation, analysis, build and actual test timings. Explicit test
   preparation remains fresh, so do not attribute library reuse savings to it.
7. Review calibration, then record a numeric unchanged-preparation ratio and
   absolute-time budget, statistic, repetitions and workload identity in a
   versioned budget record. Preserve its hash before any #7 qualification run.
   The linked budget records this declaration. It must not be revised
   retrospectively to pass #7.

Useful existing end-to-end entry point:

```sh
python3 tools/probe_serilog_performance.py --source <pinned-git-source> \
  --packages <acquired-package-cache> --output <new-evidence-directory> \
  --repetitions 5 --host-note <actual-load-and-power-observation>
```

The existing harness measures fresh preparation. The new
`tools/probe_preparation_performance.py` supplies the separate library-reuse
measurement path for steps 3–5. Do not interpret an unchanged Bazel-action case
as preparation reuse. Invoke it with `--source`, `--entries`, `--output`,
`--repetitions 5` and an honest `--host-note` describing desktop load.

The first native run in Documents encountered concurrent File Provider metadata
changes and a duplicate generated tool DLL. The identity guard correctly
rejected the unstable tree. The worktree and native state were moved to an
unsynchronized local directory and generated tools rebuilt. That rerun passed
all 17 original reuse cases. The probe now explicitly creates the empty package
directory so a package-free restore cannot leave fresh fallback without its
required package root. No input-stability check was relaxed.

## #6: candidate correctness matrix

| Required case | Starting point | Required qualification (now recorded in findings) |
| --- | --- | --- |
| Cold and unchanged reuse | `probe_preparation_reuse.py` | Rerun candidate; record expected/observed work |
| Source additions/removals | Discovery probe detects membership changes | Consume refreshed preparation and verify compilation/output changes |
| Imports and optional/glob imports | Discovery probe invalidates nested/optional/wildcard inputs | Verify preparation refresh and resulting graph/actions |
| Reference metadata | XML eligibility rejects unqualified metadata | Verify fresh fallback preserves configured graph and no stale reuse |
| Restore/package changes | Discovery invalidation and package integrity tests | Exercise retained valid and corrupt package changes through consumption |
| Configuration changes | Unit fallback and discovery rejection | Native fresh execution or actionable rejection, never stale reuse |
| Missing/corrupt payload, manifest and pointer | Reuse native probe | Rerun all recovery controls |
| Interrupted publication | Native staged/pointer-switch controls | Verify prior pointer intact and no partial consumer published |
| Concurrent consumers | Native two-process serialization | Rerun with both results and lease ordering retained |
| Tool/controller changes | Native runner-change and identity tests | Record invalidation and new-process requirement |
| Producer-free relocation | Small-graph and Serilog reuse probes | Actual execution after producer deletion; distinguish fresh actions from disk-cache hits |
| Explicit test requests | Fresh-fallback probe and approval-test harness | Confirm no reuse certificate; force actual recovered approval test |

Existing native entry points, all inside the pinned Nix shell:

```sh
python3 tools/probe_discovery_contract.py --output <new-discovery-evidence>
python3 tools/probe_preparation_reuse.py --output <new-reuse-evidence>
python3 tests/preparation_reuse/probe_serilog_reuse.py \
  --source <pinned-git-source> --packages <acquired-package-cache> \
  --output <new-serilog-reuse-evidence>
python3 tools/probe_serilog_test_adapter.py \
  --source <pinned-git-source> --packages <acquired-package-cache> \
  --output <new-approval-evidence>
```

Retain each command, exit status, logs, candidate identity, expected and observed
action set, graph identity and runtime/test oracle. Certificate invalidation
alone does not prove that the consumer executes the refreshed plan. The complete matrix now has evidence in the linked findings. GitHub CI is not required for this
local scope and has not been dispatched.
