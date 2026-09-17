# MSBuild parity work

Local macOS ARM64, pinned SDK 10.0.400/Bazel 8.4.2, release base c4708f6.
Changes are measured independently; this is not a new platform qualification.

## Stage 1: unchanged preparation

Reuse now qualifies the package-free scale fixture's five literal SDK switches.
Other values/property expressions remain ineligible. Snapshot traversal reuses the
resolved parent for non-link children while retaining link resolution, namespace,
content and final entry-signature checks. Controller/executable identities hash
bytes directly instead of expanding them into hexadecimal JSON. Output collision
checks sort path components instead of comparing every pair.

100-project fan, same source, five unchanged samples per implementation after a
fresh seed, including lease teardown: original algorithms with only the same
fixture eligibility have median 0.934s; candidate 0.840s (10.0%, 0.094s saved).
Most of the improvement over fresh preparation comes from enabling the existing
validated reuse path, not the traversal optimization. This reuses a process-local
explicitly trusted system Nix store session; first-request capture remains 10.717s.
Fresh preparation from the preceding profile was 7.833s plus initial export 5.980s.
Those are different operations, not paired speedup samples.

68 preparation identity, corruption, mutation, source-refresh and contract unit
checks pass. Full-workflow and edit validation follows in subsequent stages.

## Stage 2: reference/runtime split

Opt-in `compile_boundary=True` / `--compile-boundary` separates stable reference
bundles from runtime bundles. Compiler actions use verified reference bytes and
SDK replay metadata. Separate runtime actions combine current implementation
artifacts and SDK-generated project dependency metadata. The latter is necessary:
reference-only compilation does not discover implementation-only assembly edges.

Eligibility is deliberately package-free net10.0 SDK projects with ordinary
project references; custom targets/tasks, package/project generators, arbitrary
references and copy-content metadata are rejected. The existing full dependency
path remains the default for other projects. Persistent preparation keys include
the mode. The action boundary remains native sandboxed with remote execution off.

Ten-project fan: fresh 13.130s, unchanged 1.784s, shared body edit 5.862s, disk
recovery 4.360s. Compiler counts are respectively 10, 0, 1, 0. Runtime output passes
all four cases and recovered bundles equal the producer's bytes/modes. These are
single diagnostic command timings, excluding preparation. Fresh cost increased
versus the earlier 11.241s; the third stage addresses execution overhead.

Retained failed prototypes exposed writable-mode handling on copied Bazel inputs,
SDK executable metadata, transitive DLL staging and runtime dependency metadata.
They were fixed before the passing native matrix. No failed sample is timed as a
successful speedup.

The 100-project stage-2 fan passes fresh, warm and shared-edit work/output oracles.
Command times: MSBuild 26.789/7.914/7.948s; adapter 69.735/2.346/13.308s.
The shared edit compiles exactly one project. Runtime composition remains costly;
these command times exclude initial export/preparation.

## Stage 3: avoid repeated execution work

The candidate runtime action consumes each producer's own compilation bundle,
rather than depending on repeatedly composed transitive runtime bundles. It
selects the producer's own assembly/debug/documentation files, rejects collisions,
and composes SDK-generated project dependency metadata. The compiler API bundles
remain separate. Requesting the entry target does not require producing every
intermediate project's composed runtime bundle.

Final 100-project complete-workflow results at normal verbosity (fresh once, warm/body five paired
samples; same pinned machine and two compiler slots):

| Case | Raw MSBuild | Adapter | Compilations raw / adapter |
| --- | ---: | ---: | ---: |
| Fresh | 25.759s | 70.742s | 100 / 100 |
| Unchanged median | 2.845s | 1.384s | 0 / 0 |
| New shared body median | 3.384s | 3.406s | 1 / 1 |

Preparation and lease teardown are included. Unchanged is 2.06x faster; body
edits are effectively at parity (0.7% slower). Cold remains 2.75x slower. Restore,
tool builds and application execution are outside these timings. Every resulting
application passes the independent output oracle. This is local synthetic evidence,
not a Serilog/package/test or remote-cache performance qualification.

The final ten-project native matrix passes fresh, unchanged, body edit, API edit
and producer-free disk recovery. Adapter command times are respectively
13.747/1.760/5.511/10.904/4.560s, with 10/0/1/10/0 compiler invocations.
Ordinary MSBuild compiles three projects on the API edit: transitive API inputs
remain conservative. Recovery preserves bundle contents and modes.

### Measurement correction and validation

Earlier diagnostic-verbosity raw runs emitted approximately 392-480 MB of logs
per sample. They measured raw warm/body medians of 5.419/5.584s against adapter
1.399/3.474s and overstated the speedup. The final table uses normal verbosity
and counts actual compiler command lines; cold/warm/edit counts and runtime
outputs all pass. Both modes use two compiler slots, MSBuild node reuse is
disabled, and Bazel retains its server. No binary log is collected in this final
performance comparison. Restore and tool acquisition remain setup.

Validation: 99 focused Python tests, action-runner contract/process/runtime tests,
owned .NET build/style checks, and pinned Starlark formatting/lint all pass.
The default full-bundle ten-project fresh/warm/body matrix and Serilog approval
Build/Test acceptance (cold, unchanged, data edit, exception edit, producer-free
relocation, and missing/changed input rejection) also pass. No CI was dispatched.

### Rejected execution experiment

A direct SDK mode using `BuildProjectReferences=false` and MSBuild target-result
queries passed the focused correctness matrix, but did not meaningfully improve
100-project command times: fresh 70.905s versus stage 2's 69.735s, and body edit
13.057s versus 13.308s. It also replaced MSBuild static-graph replay/isolation
semantics. The extra code and flags were removed; final results above use graph
replay with native sandboxing. A prototype complete-workflow run stopped when the
benchmark incorrectly expected compilation after reverting to an already cached
body. The final probe uses a distinct new body on every edit and passes.

Persistent workers were not introduced; cross-request state requires separate
correctness work. Whole-graph raw MSBuild batching is a separate experiment.

## Reproduction

Use the locked Nix shell, short output paths outside the checkout, serial runs,
and prebuilt tools for leased preparation. The new modes are explicit opt-ins:

```sh
python3 tools/probe_synthetic_scale.py --nodes 100 --shape fan \
  --target-framework net10.0 --compile-boundary \
  --cases fresh warm shared api recovery --output /private/tmp/parity-native
python3 tools/probe_msbuild_parity.py --nodes 100 --repetitions 5 \
  --output /private/tmp/parity-full
```

The complete-workflow probe uses a retained Bazel server and process-local
explicitly trusted system Nix-store session, measures lease teardown, executes the
resulting application after every sample, and checks compilation counts. Restore
and tool acquisition are setup and separately recorded. It builds `//:all`, the
normal entry target; the synthetic correctness probe additionally requests every
project's runtime bundle, so their command times must not be compared as identical
workloads. Every shared edit uses a distinct implementation body, and mode
order alternates. Fresh is a single diagnostic sample; warm/shared each have five
samples. No CI or remote-worker qualification is included.
