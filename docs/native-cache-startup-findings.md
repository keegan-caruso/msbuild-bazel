# Overlapping Bazel startup with input preparation

This follows the [transfer and cold-start measurements](native-cache-overhead-findings.md).
The target is time outside the single MSBuild graph action. The previous cold
profile spent 5.998 seconds there, including SDK fingerprinting, JVM startup,
module resolution, platform acquisition, analysis, sandbox setup and publication.

## Implementation

The generated controller starts `bazel query @platforms//host:host` in one
background thread while it fingerprints the full SDK and captures, validates and
stages declared input files. Query loads the platform metadata; it cannot execute
the .NET build action. Before starting the build, the controller joins the query
and propagates any failure. The query uses the same workspace and output base as
the build, so the JVM and loaded repository are reused.

The generated module explicitly declares `platforms` 0.0.11, the same version
selected implicitly by the preceding pinned Bazel 8.4.2 experiment. This makes
the query repository visible from the main module. The SDK, compilation inputs,
cache validation, sandbox execution, compiler concurrency and publication policy
are unchanged. Startup overlap runs once for each new output base; normal retained
builds do not issue another query. If a server exits later, Bazel's normal build
startup still works. The query's cost is never excluded from the build timer.

SDK capture now occurs inside the actual cold-build timed region. Previously it
was performed earlier and its duration added to cold time. Report fields record
SDK and startup durations; these overlap and must not be added together. The
preparation duration includes the join, and total time includes the whole process
through publication. Query and build each emit their own Bazel profile.

`--serial-startup` retains the control path, where the build command starts Bazel
after preparation. `--jvm-startup` retains the intermediate experiment that starts
only `bazel info release`. Neither control changes the compiler or cache policy.

## Retaining module resolution

The controller previously removed `MODULE.bazel.lock` with the generated input
workspace. A 100-project unchanged outer-hit sample took 2.506 seconds and its
profile showed 1.500 seconds recomputing the module mapping, with repeated registry
requests. The next sample took 1.016 seconds. This was unnecessary work.

Workspace regeneration now carries forward the lock bytes only when the generated
`MODULE.bazel` is byte-for-byte identical. A changed module or
`--discard-module-lock` drops the lock. All generated source/seed files are still
recreated, and Bazel remains responsible for checking the lock and repository
content digests. This preserves dependency-resolution metadata, not hidden build
outputs or an unvalidated compilation cache. A focused test checks preservation,
changed-module invalidation, forced discard and stale-source removal.

## Experiments and limitations

The first 100-project pair observed 31.914 seconds serial versus 33.378 seconds
with JVM-only overlap. Action subprocess times were almost identical: 26.346 and
26.366 seconds. Inspection found platform archive acquisition took 2.449 seconds
in the latter run versus approximately 0.35 seconds previously. This is network
variation, so the end-to-end difference cannot establish that JVM overlap itself
caused a regression. JVM-only overlap is not the default.

An initial platform-query smoke failed because the implicit platform repository
was not visible by apparent name from the generated module. No MSBuild action ran.
The explicit pinned dependency corrected that issue; failed evidence is retained
separately and excluded from timing conclusions.

All workloads remain owned package-free net10.0 Release graphs on macOS ARM64/Nix,
with loopback project/action caches. Registry and platform archive acquisition can
still use the public network. Cold observations are sensitive to those transfers;
small timing differences are not statistically established speedups. Sandbox,
package, cross-host and remote-execution limits from the preceding experiment
remain. No CI was dispatched.

## Final results: 100 projects

| Measurement | Serial control | Platform overlap and retained lock |
| --- | ---: | ---: |
| Full cold build | 32.689 s | 31.273 s |
| Action subprocess | 26.518 s | 26.578 s |
| Outside the action | 6.171 s | 4.695 s |
| Paired raw cold build | 25.288 s | 25.630 s |
| Body-edit median, three samples | 3.296 s | 3.339 s |
| Paired raw body-edit median | 3.305 s | 3.281 s |
| Stable outer-hit median, two samples | 1.318 s | 1.040 s |

Observed outside-action overhead fell by 1.477 seconds (23.9%); full cold time fell
by 1.416 seconds (4.3%). Action duration stayed nearly unchanged, supporting the
attribution to orchestration rather than faster compilation. These are individual
cold observations, not a statistical performance guarantee. The preceding
platform-overlap run without lock preservation also took 31.266 seconds cold;
lock preservation targets subsequent invocations, not the first cold request.
The final path remains 22.0% slower than its paired raw cold build. Body edits
remain near parity (1.8% above the paired raw median), with one compile and 99 hits.

The final two unchanged outer-hit samples took 1.058 and 1.023 seconds. Neither
profile contains a registry-file download, versus 155 downloads in the preceding
2.506-second outlier with the lock discarded. The serial control's two samples
also had no registry downloads: losing the lock does not cause a fetch on every
invocation, but preserving it removes this avoidable source of re-resolution.

All eight successful matrices passed application oracles, expected compile/cache
counts and paired cold/body runtime-DLL byte comparisons: three ten-project full
fault matrices and five 100-project comparisons across the controls/stages. The
final implementation also passed 19 cache unit tests, Python syntax compilation
and `git diff --check`. The failed initial query smoke is excluded.

Remaining cold overhead still includes JVM launch and external repository
acquisition, plus analysis, sandbox staging and output handling. Reusing acquired
repository metadata across separate controller sessions is the next candidate;
it must retain digest verification and account for initial acquisition cost.

## Reproduction

Inside the pinned Nix shell, use fresh short paths:

```sh
python3 tools/probe_portable_cache.py --retained --nodes 100 --repetitions 3 --no-extended --serial-startup --discard-module-lock --output /private/tmp/start-serial
python3 tools/probe_portable_cache.py --retained --nodes 100 --repetitions 3 --no-extended --jvm-startup --discard-module-lock --output /private/tmp/start-jvm
python3 tools/probe_portable_cache.py --retained --nodes 100 --repetitions 3 --no-extended --output /private/tmp/start-platform
```
