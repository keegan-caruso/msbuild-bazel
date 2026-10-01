# Runtime graph test-host qualification

The graph path builds a selected source framework and runs eight reviewed upstream
VSTest suites. The 481-compilation seed passes all selected suites. All 3,622 compiled DLL/PDB/resource files match complete-source raw MSBuild.
All eight suites preserve raw case outcomes and pass without the downloaded SDK
mounted. The earlier 474-compilation Pipelines scope also has full local replay
and body/API boundary evidence. The expanded eight-suite scope now passes
those replay, edit and failure/restoration controls too.

## Verified checkpoint

Runtime v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`), SDK 10.0.400,
Linux ARM64 and Bazel 9.2.0. The VM has four CPUs and 8 GiB; graph workers use
four MSBuild nodes. The expanded fixture declares an 8192 MiB logical worker-cache
budget; the rule default remains 4096 MiB. This disk accounting does not cap
process memory. The seed retained about 2530 MiB, so earlier cache loss does not
establish that the default budget was exceeded. These are unscored correctness checks.

| Check | Observed result |
| --- | --- |
| App/platform/Pipelines graph | 133 projects, 303 configurations, 267 compilations; managed Build passes |
| VSTest on the original 58-library source host | Fails because source-built `System.Diagnostics.TraceSource` is absent |
| Expanded library/shim/Pipelines sync | 253 projects, 536 configurations, 474 compilations; offline sync passes |
| Expanded managed Build | All 474 compilations pass, with prepared Restore and read-only worker packages |
| Expanded host declaration | 123 managed assemblies and eight native binaries; includes TraceSource, XML and 17 authored Linux shims |
| Real Pipelines suite | 577 passed / zero skips; 84 observed source-producer hashes match across VSTest, datacollector and testhost processes |
| Complete-source raw Build | 3,447 DLL/PDB/resource files match graph bytes, including reviewed shared outputs |
| Raw VSTest control | The same 577 case names and passing outcomes; the same three process roles and 84 source-producer hashes |
| Shared BinPlace ownership | 1,391 SDK-inventoried files across 231 producer configurations; one earlier CoreLib PDB declaration retained |
| Full local replay | 474 hits / zero misses; all 10,506 compared files, bytes and modes match the seed |
| Body edit | 468 hits / six misses, matching raw compiler calls; unchanged reference bytes and all 577 cases rerun |
| API edit | 457 hits / 17 misses, matching raw compiler calls; all 577 cases rerun |
| Source restoration | All 474 projects replay; exact seed files/bytes/modes and full-source raw parity return |
| SDK-absent VSTest | All 577 cases pass with only the declared host/tests and system libraries mounted; source hashes still match |
| Genuine assertion failure | Only the test project recompiles: 473 hits / one miss, matching raw; VSTest reports 576 passes / one failure and Bazel fails |
| Assertion restoration/caching | 474 replay hits, exact original outputs and 577 passes; the next unchanged test is cached |
| Wrong CoreLib hash | Observer rejects the deliberate mismatch; Bazel reports test failure without compilation |
| Small metadata generator | Generated source/assembly changes on a declared metadata-file edit; restoration replays one project with identical bytes |
| Document guard | A changed generation-target hash is rejected |

The smaller test attempt also exposed a fixture mistake: composing a layout at
its root requires `"."`, not an empty destination. No production rule changed.

## Eight-suite expansion

The reviewed combined graph has 260 physical projects, 543 configurations and
481 compilations. Bazel 9.2.0 builds all 481 projects and runs all eight suites
on the declared source host, with 118,952 passes, 64 skips and no failures.
These are unscored Linux ARM64 correctness checks.

| Selected upstream suite | Passed | Skipped |
| --- | ---: | ---: |
| Pipelines | 577 | 0 |
| Collections.Immutable | 22,544 | 0 |
| Collections | 33,438 | 0 |
| LINQ | 52,178 | 8 |
| Threading | 591 | 0 |
| Threading.Tasks | 809 | 2 |
| FileSystem | 8,662 | 54 |
| Sockets: reviewed NetworkStream filter | 153 | 0 |

The host retains 123 managed and eight native producers. It also declares the
reviewed net8.0 Formatters assembly in a private support directory. Production
rules contain no runtime-specific translation. The observer records the VSTest,
datacollector and testhost processes, plus RemoteExecutor children where used.

A qualification-only C# action adds the NetworkStream filter to the actual
SDK-generated settings. It preserves other SDK fields and combines an existing
filter with `&`. Small public-Bazel controls pass on 8.8/9.2: combine or create a
filter, preserve the host field, reject absent RunConfiguration, and restore
without compiling the tool again.

Prepare the larger scope by adding these selections to the preparation command:

```sh
--also-slice collections --also-slice threading \
--also-slice filesystem --also-slice sockets
```

Compose its host and harness:

```sh
python3 tests/graph_build/upstream/runtime_application.py \
  WORKSPACE NATIVE_WORKSPACE --include-private-frameworks
python3 tests/graph_build/upstream/runtime_suite.py WORKSPACE PINNED_VSTEST_ARCHIVE \
  --slice pipelines --slice collections --slice threading \
  --slice filesystem --slice sockets
# Run //:runtime_suites with the worker options below.
python3 tests/graph_build/upstream/runtime_settings_synthetic.py NEW_DIRECTORY
# Repeat the small fixture with --version 8.8.0.
```

The expanded seed reports zero hits / 481 misses. Adding roots changed the cache
contract; seven additional compilation nodes did not mean seven actual misses.
Complete-source raw Build uses the same 260 projects / 543 configurations. Its
shared BinPlace inventory is exactly unchanged: 1,391 files across 231 producer
configurations, plus the earlier declared CoreLib PDB. All 3,622 compiled products
match graph bytes. All eight suites preserve case counts, outcomes and the 64
skips; only the existing reviewed unstable MemberData displays are normalized.
Observed source-producer hashes match in VSTest, datacollector, testhost and the
72 RemoteExecutor child observations across threading and filesystem suites.

SDK-absent execution repeats all eight suites with identical outcomes. Its first
filesystem attempt exposed two namespace differences: UID 0 without DAC
capabilities failed privileged-write tests, and missing `/dev/console` removed
eight discovered cases. The passing namespace keeps the matching DAC capabilities
and conditionally binds that VM device. It still mounts no SDK; no case or filter
was removed. A deliberately wrong CoreLib hash fails fast.

The expanded replay/edit controls pass on Bazel 9.2.0:

| Control | Project-cache hits / compilations | Verified result |
| --- | ---: | --- |
| Forced full replay | 481 / 0 | All 10,780 compared files, bytes and modes match; all eight test results cached |
| Body edit | 475 / 6 | Raw Csc also compiles six; reference bytes unchanged; all suites rerun with original outcomes |
| Body restoration | 481 / 0 | Exact original files/modes and raw compiled-byte parity return |
| API edit | 464 / 17 | Raw Csc also compiles 17; reference bytes change; all suites rerun with original outcomes |
| API restoration | 481 / 0 | Exact original files/modes and raw compiled-byte parity return |
| Assertion failure | 480 / 1 | Only the Pipelines test project recompiles; one case fails and Bazel fails; the other seven suites pass |
| Assertion restoration | 481 / 0 | All original passing/skipped outcomes and raw bytes return |
| Wrong CoreLib hash | No compilation | All eight tests fail; failures are not cached |
| Observer restoration, then no-op | No compilation | All suites pass, then all eight successful results are cached |

All edit/restoration rows compare the complete set of 3,622 compiled products
against the full-source raw graph. Native construction and prepared Restore do
not rerun. Raw binary logging and test execution make these correctness rows,
not scored build timings. Run the existing controller with `--all-suites` to
select this reviewed 481-compilation scope:

```sh
python3 tests/graph_build/upstream/runtime_suite_controls.py \
  WORKSPACE RAW_DIRECTORY NEW_CONTROLS_DIRECTORY --output-base WARM_BASE --all-suites
```

Actual 8.8 suite execution and paired timings remain open.

## Declared inputs

The reviewed shim stub target generates C# from `ForwardedType` metadata before
`CoreCompile`. Its document hash and target name are pinned, and each of the 19
stub projects declares that item as metadata. Generated files remain in the
SDK intermediate output directory.

The pinned JavaScript import generator declares an empty IDE `Folder` item.
Its project hash and scoped metadata declaration preserve that fact without
inventing recursive file inputs. The reviewed source contains no translations
in that empty folder.

The larger graph adds the authored API compatibility baseline
`Microsoft.Bcl.Memory/9.0.0`, SHA-256
`102832679dd7a89a117197b142972d12ad671c55ee5b862a152c7b125b1a7bb5`.
The Expressions project additionally needs its authored `CompatibilitySuppressions.xml`,
discovered inside SDK targets. Its owning project hash is pinned. API validation
remains enabled. All declarations are qualification mappings;
production rules contain no runtime-specific special case.

Reproduce preparation with an explicit feed containing the pinned archives:

```sh
python3 tests/graph_build/upstream/runtime_prepare.py \
  SOURCE_ARCHIVE PACKAGE_FEED NEW_DIRECTORY \
  --slice loaded-common --also-slice loaded-platform \
  --also-slice loaded-libraries --also-slice loaded-shims \
  --also-slice pipelines --prepared-restore --worker-cache-mb 8192
```

Compose and run the actual harness after preparation:

```sh
python3 tests/graph_build/upstream/runtime_application.py WORKSPACE NATIVE_WORKSPACE
python3 tests/graph_build/upstream/runtime_suite.py WORKSPACE PINNED_VSTEST_ARCHIVE
# From WORKSPACE, using the repository's absolute launcher path:
RULES_REPOSITORY/scripts/bazel-launcher.sh --output_base=NEW_BASE \
  test //:pipelines_suite --jobs=1 --strategy=MSBuildGraph=worker \
  --worker_sandboxing --worker_max_instances=MSBuildGraph=1 \
  --disk_cache= --remote_cache= --test_output=errors
```

VSTest 17.14.1 and the resolved xUnit adapter archives have declared hashes.
The source-host observer rejects excluded installed framework components.
The first passing graph reports zero hits / 474 misses; failed overall builds
were not saved as project snapshots. Setup elapsed time is unscored.

Run the independently reproducible small fixture after building ProjectSync,
with the pinned SDK and Bazelisk overrides set:

```sh
python3 tests/graph_build/forwarded_types.py NEW_LINUX_ARM64_DIRECTORY
```

It runs public sandboxed graph workers with remote caches disabled. Project-file
edits require resync; the replay control instead edits an explicitly declared
metadata file. Large logs and report JSON remain outside Git.

Compare the completed graph against a fresh full-source raw Build and real VSTest:

```sh
python3 tests/graph_build/upstream/runtime_full_source.py \
  SOURCE_ARCHIVE WORKSPACE NEW_RAW_DIRECTORY --inventory-only
python3 tests/graph_build/upstream/runtime_suite_verify.py \
  WORKSPACE NEW_RAW_DIRECTORY NEW_PARITY_DIRECTORY --sdk-absent
```

The raw control uses the same managed graph, SDK, global properties, stable paths
and four MSBuild nodes without the project-cache plugin. Its VSTest host replaces
all 123 managed binaries with raw products. The eight native binaries are shared
source-built producers; this does not qualify an independent native rebuild.

The raw contract may differ only by added output files proven by that completed
SDK inventory. Changed inputs, properties, removed outputs and unreviewed additions
are rejected. Capture and compare the larger edit controls using a retained,
successful graph worker and full-source raw outputs:

```sh
python3 tests/graph_build/upstream/runtime_suite_controls.py \
  WORKSPACE RAW_DIRECTORY NEW_CONTROLS_DIRECTORY --output-base WARM_BASE
```

This forces a graph action with an unused declared input, checks project-cache
hits, and compares body/API misses with actual raw Csc calls. Binary logging is
used for raw diagnostics, so these rows are not timing comparisons. Restore and
native construction do not rerun on the edits. A genuine assertion failure changes
one expected exception parameter name; only that test project recompiles. A first
fixture check failed because xUnit truncated its diagnostic marker. The passing
control uses a short unique marker and starts from a successful original suite.

## Remaining gates

Repeat relevant actual-suite controls on Bazel 8.8.0 and capture larger paired
build timings separately from test execution.
Independent cache consumers, native source/header/tool mutations and broader edit
scenarios remain separate roadmap gates. Build and test timings must be separate.

A disk-full interruption made the qualification filesystem read-only. That trial
is excluded. After preserving diagnostics, restarting only the owned build VM
and removing obsolete staging, host free space reached 62 GiB before the retry.
No passing test or performance claim is derived from the interrupted run.

The separate [publication audit](runtime-graph-publication.md) identifies staged
input bytes that may be removable after consumer and ownership review.
