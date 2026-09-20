# Read-only package inputs in Bazel project actions

The qualified macOS owned workflow now defaults to borrowing when both
`project-actions` and `package-actions` are enabled. Set `borrow-package-inputs: false`
to retain private package copies. Explicitly enabling it without both prerequisites
is rejected. The workflow emits `borrow_package_inputs` on each compile rule,
which passes `borrowPackageInputs` to the native runner. Direct Starlark and runner
callers still default to false. Package-origin output compaction is independent
and remains opt-in.

## Behavior and integrity

The existing read-only input implementation now runs inside actual Bazel project
actions. It creates private logical NuGet paths that link to declared package files,
avoiding a byte copy for each project. Writable package inputs are rejected. Source
files and generated restore metadata remain private files; replacing restore
metadata breaks a link before writing. The existing prepared-payload, plugin input
and exit validation checks remain enabled. Borrowed package bytes are rehashed
before successful return. No mutable global NuGet cache is introduced.

This changes local execution and materialization cost. The declared package
closure and Bazel's remote-cache ownership are unchanged. A full action-cache hit
still skips execution and package downloads.

## Orchard entry measurement

Three alternating pairs use the same runner binary, prepared inputs and output
paths, changing only the borrowing flag. This is the CMS entry after its 201
dependencies are available, outside Bazel scheduling and remote transfer.

| Mode | Samples (seconds) | Median |
|---|---|---:|
| Copy | 24.715, 20.986, 22.979 | 22.979 |
| Borrow | 20.325, 18.188, 20.377 | 20.325 |

Borrowing saves **2.654 seconds (11.5%)** in this comparison. All six runs have
identical 6,932-file logical entry/API/runtime outputs. Each run consumes 12,017
package files totaling 2,146,600,383 logical bytes.

Median package placement falls from 1.615 to 0.668 seconds. Plugin workspace hash
checks fall from 5.168 to 2.338 seconds, while the additional borrowed-input exit
check costs about 1.108 seconds. These phases explain the improvement, but their
separate medians should not be added as an exact wall-time decomposition.

Raw measurements: `/private/tmp/readonly-packages-measure`.

## Complete Orchard workflow

One fresh 202-project workflow per mode ran sequentially on macOS ARM64 with
SDK 10.0.400, Bazel 8.4.2 and two jobs. Both used the same state path, cleared
between runs, separate initially empty loopback caches, and the same source and
verified NuGet archives/repository download cache. Each run executed all 202
compiles and bindings, 287 package extractions, discovery and restore, with no
action-cache hits for those actions. Cache publication is included in wall time;
runtime verification is outside it.

| Measurement | Copy | Borrow |
|---|---:|---:|
| Complete workflow | 652.488 s | 616.925 s |
| Package placement, sum across actions | 51.922 s | 24.094 s |
| Declared package-file appearances | 279,531 | 279,531 |
| Logical package bytes across actions | 57,383,869,534 | 57,383,869,534 |

The observed workflow reduction is **35.563 seconds (5.45%)**. This is one full
run per mode, not a statistical guarantee. Summed action times overlap across
two jobs and cannot be subtracted directly from wall time. The payload byte count
follows declared input links; the runner's existing `packageBytes` diagnostic
counts sandbox symlink lengths in native Bazel runs and is not used for that total.

Both applications returned HTTP 200 and served the C#, Razor and CSS markers.
They have identical 3,457-file membership; 3,299 files are byte-identical and
79 DLL/PDB pairs differ. This is consistent with the existing independent-build
Razor path limitation, not a claim of full independent-producer byte parity.
The six same-path entry runs above remain the strict byte-equivalence control.

The default is enabled only through the already platform-restricted owned workflow:
the positive full-graph result, paired entry measurements and native cache controls
support using it there. Other platforms remain unqualified; no CI was run.
Raw full-workflow evidence: `/private/tmp/readonly-packages-orchard`.

## Native cache acceptance

The four-project, two-package test verifies:

- All four compile actions use borrowed inputs, with 70 package-file appearances.
- Application hashes match the dense copy baseline and the application prints `11`.
- Deleting the producer and using a fresh worker gives zero compiles and downloads
  no package payload files; application hashes and output remain identical.
- A dependency body edit runs one compile and prints `21`. Newtonsoft.Json
  materializes (24 files), while the unrelated PolySharp package stays remote.
- Invalid publication and retry controls pass.

Existing unit controls reject writable inputs and post-link content mutation,
and verify that removing private links leaves the original package intact.
Raw native evidence: `/private/tmp/readonly-packages-native`.

After enabling the workflow default, a second native run omitted the borrowing
flag and enabled package-origin outputs. All four actions still borrowed package
inputs. Producer-deleted recovery and dependency/entry edits passed, including
sparse dependency consumption. The package-origin option retains its documented
runtime package over-fetch tradeoff. Evidence: `/private/tmp/readonly-packages-default-native`.

Owned builds with warnings as errors, ActionRunner.Tests, 69 applicable workflow
tests and 33 preparation tests pass. One Linux-only workflow test was skipped on
macOS. C# formatting, buildifier, Python syntax and `git diff --check` pass.
See [the recorded measurements](read-only-package-actions-evidence.json).

## Reproduction

Build the owned tools first, then set `RULES_MSBUILD_DOTNET_ROOT` and
`RULES_MSBUILD_BAZEL` to the pinned SDK and Bazel paths.

```sh
python3 tests/remote_workers/direct_cache_probe.py \
  --acceptance-only --borrow-package-inputs \
  --output "$NEW_ACCEPTANCE_DIRECTORY" \
  --repositories "$BAZEL_REPOSITORY_CACHE" --cache-binary "$BAZEL_REMOTE"

python3 tests/remote_workers/optimization_probe.py --borrow-package-inputs \
  --request "$ORCHARD_ACTION_REQUEST" --execroot "$ORCHARD_EXECROOT" \
  --output "$NEW_ACTION_MEASUREMENT" --dotnet "$DOTNET" \
  --baseline "$NATIVE_RUNNER" --runner "$NATIVE_RUNNER"

python3 tests/remote_workers/readonly_package_workflow_probe.py \
  --request "$ORCHARD_WORKFLOW_REQUEST" --output "$NEW_WORKFLOW_MEASUREMENT" \
  --cache-binary "$BAZEL_REMOTE"
```

The full-workflow probe owns its new output directory and clears only its own
baseline Bazel state before the candidate run. It preserves the exact state path,
starts an empty pinned cache per mode, records aggregate staging times and checks
the running application outside the build timer.
