# Cold-build discovery session reuse

The pinned Orchard workload still spends most cold-build time in isolated project
compilation. This change removes repeated MSBuild session setup and reference
negotiation within discovery; it retains Bazel's project actions and cache boundaries.

## Measured results

| Measurement | Before | After |
|---|---:|---:|
| Standalone graph export, two-run median | 68.241s | 22.990s |
| Sandboxed discovery action diagnostics | 137.277s | 91.815s |
| Complete cold workflow | 707.368s | 662.914s |

Standalone runs were baseline, candidate, candidate, baseline; the intervening
resolution-only experiment took 66.377s. All five 202-project exported manifests
were byte-identical. Candidate and baseline standalone pairs used the same restored
source and packages. The full workflow numbers are single runs, so their difference
also includes host/filesystem variation; it is not a statistically controlled speedup.

The workflow executed all 202 bindings and compilations, 287 package extractions,
and restore/discovery with zero action-cache hits. It retained verified NuGet
archives and Bazel repository downloads, so this is cold build state, not an empty
machine or a network package-download benchmark. Controller validation and gated
remote publication are included. The source is pinned Orchard
`04467a3438d4255627c1a478598a1585b3ff2947` plus the existing benchmark markers;
the new producer contains the two CSS/Razor markers added after the old producer.
The application contains 3,457 files. Of these, 3,293 match the prior recovered application
exactly; 164 module DLL/PDB files differ. The app returned HTTP
200 and served the C#, CSS and Razor markers. Runtime validation is outside the timer.

### Existing Razor reproducibility limitation

The additional cross-cold-build byte comparison failed. All 82 differing DLLs have
matching embedded resources under the existing PE inspection probe. 73 of the 82
also have matching method IL/signature records; the remaining differences are
retained in the evidence and are not treated as binary equivalence. All 82 differing
PDBs have matching document records after
normalizing only embedded absolute worker roots and generated Razor tag-helper
offsets. These are the previously recorded differences in
`/private/tmp/orchard-pilot-evidence/razor-path-parity.json`; absolute worker paths
are visible in the old baseline artifacts as well. This is diagnostic classification,
not proof of full binary equivalence. No bytes were rewritten and the evidence
retains `crossBuildByteParity: false` and the failed overall parity gate.

The discovery optimization has exact graph parity and passing runtime checks. It
does not fix Razor output reproducibility or qualify byte-identical independent
cold producers. Fix that separately before making that claim.

An earlier attempt was interrupted for disk headroom after 264.651 seconds and
published zero cache objects. Its reports remain under
`/private/tmp/orchard-cold-session-interrupted`; it is excluded from the timing.
Cleanup completed before the accepted workflow run, which began with over 13 GiB free.

## Implementation and safety

Graph construction now owns one `ReferenceFrameworkNegotiation` build session
instead of creating an engine for every project's `PrepareProjectReferences` call.
SDK target results can be reused across references to the same configured project.
A second action-local session resolves `BazelGraphExportContract` across disposable
project instances. Both sessions end before export returns, including failure paths.
There is no persistent worker, cross-action memoization, broader sandbox allowance,
or removal of source/package validation. Source projects and authored framework
selection stay unchanged.

The regression test exports Release and Debug instances of the same path, each
with a different declared input, in both entry orders. It verifies that configured
inputs remain distinct and no subject compilation occurs. All 23 graph/framework
acceptance tests pass. Owned tools build without warnings; formatting, five style,
33 preparation and 69 workflow tests pass (one Linux-only skip). No CI run.

## Remaining cold-build costs

The original Bazel trace puts compilation at roughly 478 seconds of wall time,
after a 140-second discovery action. Across the newly measured compile actions,
phase totals are:

| Phase | Aggregate action seconds |
|---|---:|
| sourceAndRestore | 106.223s |
| sessionSetup | 138.051s |
| msbuild | 477.572s |
| cleanup | 50.576s |

These totals overlap across concurrent actions; they must not be added to obtain
workflow wall time. `msbuild` includes the cache plugin's dependency validation and
output capture, not just the C# compiler. `cleanup` also contains API/runtime
projection work before scratch removal.

The next profiling target is repeated package/dependency staging and validation in
project actions, particularly the final three application projects. Preserve
per-project remote-cache keys and actual SDK behavior while reducing those copies
and repeated dependency scans. Persistent compiler/worker reuse is a separate,
larger isolation change and is not implemented here.

## Reproduction and evidence

The workflow request, full reports, action trace, phase diagnostics and runtime log
are retained under `/private/tmp/orchard-cold-session`. The standalone comparison
requests and logs are under `/private/tmp/cold-export-repeat`. Both use the pinned
Nix SDK. The owned workflow command is:

```sh
dotnet tools/Preparation/bin/Release/net10.0/Preparation.dll owned-workflow \
  --request /private/tmp/orchard-cold-session/request.json
```

See [machine-readable evidence](cold-build-performance-evidence.json) and the
[previous runtime/recovery measurements](runtime-recovery-performance.md).
