# Project-owned structural inputs

The generated per-project compile targets previously all consumed the same
`project_structural_inputs` filegroup. A resource, Razor or static asset edit
therefore changed every compile action, including unrelated projects.

Project layout export now records a sorted `structural` path list from the
qualified MSBuild graph. It includes non-C# workspace inputs for the project and
its dependency closure, plus graph-wide inputs. This follows evaluated ownership,
so linked files and imported props/targets outside the project directory remain
inputs. Generated `obj` metadata is provided by the bound restore plan, and NuGet
payloads remain shared until the package-scoping follow-up.

The generated BUILD uses that list for each compile action. Root configuration
files that the native plan adds implicitly remain explicit inputs. Discovery
validates the declarations before compilation; missing, extra, unsafe or stale
ownership declarations fail. Old layouts without `structural` retain the shared
filegroup until regenerated, preserving compatibility and conservative behavior.

This first change deliberately keeps whole-graph discovery and per-project
binding. A structural edit still reruns discovery. Binding produces unchanged
plans for unaffected closures, allowing Bazel to reuse their compile actions.
Consumers within the changed project's dependency closure can still recompile.
Removing resource contents from discovery requires a separate qualified split;
this change does not silently assume that project evaluation never reads them.

## Validation

- `bash scripts/check-dotnet.sh`: passed, including 52 workflow tests with one
  Linux-only skip on macOS, preparation tests, builds and style checks.
- Layout controls exercise linked resources, dependency inputs, graph-wide
  imports, omitted/extra ownership, unsafe paths and legacy layouts.
- Native four-project acceptance (`tests/remote_workers/project_input_probe.py`):
  linked resource and local import changes each compiled exactly two projects;
  shared import changes compiled all four; declaration reuse and no-op compiled
  none. Resource/local-import totals were 7.484/7.402 seconds; no-op was 0.647 s.
  The probe checks exact project identities and updated embedded-resource bytes.
  These small-fixture timings are correctness evidence, not Orchard speedup.
- The exported Orchard layout has 202 projects. The Setup stylesheet belongs to
  four dependency closures, and the median project has 29 structural workspace
  paths. These are declaration counts; execution results follow below.

## Requested sequence

1. Narrow project inputs and measure iteration cost (this change).
2. Finish Orchard asset and generator correctness checks using the new graph.
3. Integrate the separate NuGet extraction prototype.
4. Narrow per-project package inputs.
5. Repeat cold, fresh-worker remote recovery, no-op and edited-input benchmarks.

## Orchard changed-input result

| Case | Total time | Compilations |
| --- | ---: | ---: |
| Previous shared-input stylesheet edit | 1,108.482 s | 202 |
| Scoped stylesheet edit | 651.774 s | 4 |

The scoped edit took **41.2% less time (1.70x faster)** in this single before/after
comparison on the same Mac. It is not a repeated statistical benchmark or a
remote-worker timing claim. The scoped edit ran without another test build;
the original qualification included some overlapping prototype work.

All 198 unrelated projects avoided compilation. The two Setup output files
(`OrchardCore.Setup.dll` and its PDB) changed; the other 3,455 application files
matched the scoped baseline byte-for-byte. The Production runtime returned
HTTP 200 and served the new CSS marker, plus the earlier C# and Razor markers.
The application was stopped after verification.

This remains too slow for the desired iteration experience. Discovery still
costs 305.356 seconds, and all 202 project bindings execute. NuGet inputs are
still global. Cold build cost is unchanged, and an independent fresh-worker
remote-cache qualification of this change remains part of the later benchmark
step. No Linux CI, push or merge was performed.

Three consecutive no-ops took 19.066, 16.064 and 12.693 seconds (median
16.064); all executed zero discovery, binding and compile actions. The older
no-op sample was 13.396 seconds. These samples show warm-up variability and
do not establish a no-op speedup.

The subsequent [combined qualification](orchard-package-qualification.md) completes
package integration/scoping and fresh remote recovery, and reports all final
iteration timings. Its results supersede the pending follow-up status above.
