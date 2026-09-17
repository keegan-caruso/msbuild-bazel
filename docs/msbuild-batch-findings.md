# Raw MSBuild whole-graph experiment

## Result

One native-sandboxed Bazel action can hand the entire graph to ordinary MSBuild,
removing repeated per-project process startup, graph construction and replay.
This substantially improves cold builds but makes a source-edit cache miss build
the whole graph. It is an experimental synthetic-only path, not the default.

100 package-free net10.0 projects in a fan, local macOS ARM64, SDK 10.0.400,
Bazel 8.4.2; two compiler slots; normal verbosity:

| Case | Raw MSBuild | Whole-graph action | Compilations raw / action |
| --- | ---: | ---: | ---: |
| Cold (one sample) | 26.026s | 32.299s | 100 / 100 |
| Unchanged (median of 3) | 2.941s | 0.447s | 0 / 0 |
| Distinct shared body edits (median of 3) | 3.440s | 26.925s | 1 / 100 |

The action is 24.1% slower than raw MSBuild on the cold sample. Compared with the
separate fine-grained run's 70.742s cold result, 32.299s is a 54.3% reduction.
Those are serial runs on the same machine, not a statistically qualified speedup.
Fine-grained body edits remain 3.406s, roughly raw MSBuild parity. Whole-graph
batching is unsuitable as a blanket replacement for incremental project actions.

The normal-verbosity repeat corrects the original diagnostic comparison, which
produced hundreds of MB of raw logs per sample. The diagnostic batch run measured
33.612s cold, 0.470s unchanged and 29.238s edited; its corresponding raw numbers
were 27.039/5.703/6.130s. Use the normal-verbosity table for conclusions.

## Implementation and boundary

`tools/probe_msbuild_batch.py` owns and generates both fixture trees. It declares
all source files and normalized restore files, compares complete content snapshots
before/after copying, and omits all prior compiler bin/obj state. This avoids an
upfront adapter graph export: raw MSBuild discovers and schedules the graph inside
the action. Tool builds and restore are separately recorded setup. Source copying,
Bazel startup on cold, SDK input declaration, staging, compilation and output
publication are timed. The app oracle runs untimed after every sample.

`bazel/batch.bzl` invokes the .NET ActionRunner's experimental `--batch-request`
branch. It runs ordinary `Build -graphBuild -isolateProjects -m:2` without the
replay plugin, keeps native `darwin-sandbox` execution, blocks networking and
remote execution, and publishes the entry's runtime directory with an artifact
manifest. It does not produce a GraphBundle replay provider. Requests and SDK
imports are explicit action inputs. Compiler evidence counts actual normal-log
compiler command lines; the probe checks zero or exactly 100 invocations and
checks the application result on every run. Raw edits compile exactly one project.

The probe is intentionally limited to the generated package-free fixture. It is
not a general user-workspace snapshot API, a package/test implementation, a
persistent incremental MSBuild worker, or a remote-cache correctness claim. It
retains the existing local SDK/host-closure limitations. Bazel retains its server;
MSBuild node reuse is disabled in both modes. The final combined branch also
passes the ten-project normal-verbosity batch smoke and owned validation gates.

## Next architecture step

Measure fixed groups of projects instead of one project or the entire solution.
Keep high-fan-out, frequently changed dependencies in separate groups with stable
API boundaries; let MSBuild schedule the projects within other groups. Choose
groups from measured evaluation/startup cost and edit/cache-miss frequency.
Cross-group dependency-result capture and runtime composition need correctness
coverage before adopting this. Switching from a coarse action to fine actions
does not automatically populate their distinct Bazel cache entries.

## Reproduction

Run serially inside the locked Nix shell. On this pinned macOS SDK, its external
Nix imports must be declared explicitly:

```sh
python3 tools/probe_msbuild_batch.py --nodes 100 --repetitions 3 \
  --output /private/tmp/batch-repro \
  --sdk-import /nix/store/dfhdbgnvv0jm1ld0hrzfaklgigvl7bzp-extra.targets \
  --sdk-import /nix/store/hm53cqanyh9f8dl3bij21iyhvk1mlb30-sign-apphost.proj
```

This command uses short paths for the macOS .NET debugger transport limit.
See [the fine-grained findings](msbuild-parity-findings.md) for the preceding three
stages, full-workflow results, default-path regressions and rejected direct-SDK
experiment. No CI or remote performance qualification was run.
