# Four cold-build experiments

These changes do **not** meet the goal of approaching raw MSBuild performance.
The measured full direct-cache build is still 10.2 times the ordinary raw clean
build (9.7 times raw restore plus clean build). Keep the distinction between
qualified optimizations and prototypes explicit.

| Change | Measured scope | Before → after | Disposition |
|---|---|---:|---|
| [MSBuild host reuse](worker-session.md) | Eight isolated project actions | 37.300 → 32.738s | Prototype; 12.2% median, 6.8% against warmer baseline. Production worker isolation and Roslyn sharing remain open. |
| [Borrowed validation](borrowed-input-validation.md) | Orchard entry action | 20.065 → 19.709s | Enabled for borrowed inputs; 1.8%. Cross-action digest reuse is not implemented. |
| [Discovery reuse](discovery-closure-reuse.md) | Complete 202-project discovery/templates | 90.544 → 83.385s | Enabled; 7.9%, all 1,421 files identical. |
| [Direct publication/upload overlap](action-upload-overlap.md) | Full fresh Orchard workflow | 585.023 → 574.434s | Opt-in; single pair, only 1.8%. Independent-build Razor variation remains. |

These percentages describe different scopes and must not be multiplied into a
claimed overall speedup. The full gated/direct pair includes the validation and
discovery changes but leaves the worker prototype off.

## Updated raw comparison

Same Orchard source, Release, pinned SDK 10.0.400, two MSBuild nodes, no node reuse,
202 compiler invocations per clean build. Package restore uses an existing local
package cache/feed; Bazel uses existing package archives and an empty action cache.
Each raw clean build removes every project's bin and obj/Release directories.
No other build benchmark runs concurrently. Compiler sharing is the only changed
raw build property between these two samples. These are single samples, not
statistical medians or machine-cold measurements.

| Raw operation | Seconds |
|---|---:|
| Restore with available local packages | 3.122 |
| Clean build, compiler sharing disabled | 145.704 |
| Clean build, compiler sharing enabled | 56.326 |

Direct adapter workflow: 574.434s, versus 56.326s ordinary raw clean build or
59.448s including raw restore. Against raw without compiler sharing, the ratio
is 3.9 times. The adapter also performs isolation, discovery, artifact projection,
validation and cache publication; raw MSBuild does not produce equivalent cache
artifacts. These differences explain scope, not an acceptable performance result.

Compiler sharing saves 89.4s in the raw comparison. The current worker prototype
only reuses the MSBuild host; it does not obtain that compiler-server benefit.
The next substantial work remains a qualified persistent MSBuild/compiler worker
and an immutable input contract that lets separate actions avoid rechecking the
same dependency/package bytes. The completed within-action validation change is
not a substitute for that contract.

Direct producer-deleted remote recovery takes 27.875s, executes zero compilation,
restore, discovery, binding or package extraction, and reproduces all 3,457 app
files exactly. That validates the expected cache-hit path, while the cold path
still misses the performance goal.

Evidence and limits are linked above. Reproduce the raw comparator with
`tests/remote_workers/raw_full_graph_probe.py`; retained raw logs and binlogs are
under `/private/tmp/action-upload-raw-msbuild`. No CI or main-branch merge was run.

## Subsequent Linux worker implementation

The original table above records the four earlier experiments. The
[opt-in Linux persistent compiler worker](linux-persistent-compiler.md) now
implements both MSBuild/Roslyn reuse and a bounded verified-input store.
The 256 MiB synthetic package case measures 0.984s fresh actions, 0.490s with
compiler/host reuse, and 0.127s with input reuse as well. Mutation/isolation
controls and producer-state-deleted HTTP action-cache recovery pass. These
small action results do not replace the 574.434s full Orchard measurement;
a new large-graph comparison is still required.

## Direct prepared dependency follow-up

[Direct dependency consumption](direct-prepared-dependencies.md) reduces the
Orchard web entry action from a warmed 16.080s staged control to 14.008/14.004s,
with all 6,932 files identical. It removes 11,045 of 11,799 dependency placements;
the remaining 754 are SDK manifests requiring path rebasing. This is a measured
12.9% action reduction, not an updated whole-graph or raw-MSBuild ratio.
