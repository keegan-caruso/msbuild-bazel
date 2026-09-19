# Resource-only edits without discovery

Existing evaluated resource files now enter the same Bazel per-project binding
path as C# bodies. Restore and discovery receive file names with empty body
placeholders. Their action inputs retain structural files, package declarations
and the complete file namespace. The owning project's binding action hashes the
real resource bytes; compilation and runtime composition consume current outputs.

## Scope and invalidation

The qualified body suffixes cover CSS, JavaScript, Razor, XML/RESX, HTML, text,
SVG/raster images, fonts, Liquid and PO files. Only evaluated `resource` or
`content` items qualify. Other suffixes and additional/configuration inputs remain
structural. A source/resource path also used for an import, project, restore,
analyzer or additional-input role fails the split, including case aliases on
macOS. Package-owned and generated `obj` files retain their previous handling.

The generated BUILD file declares evaluated resource names explicitly. Body-only
edits therefore leave restore/discovery keys unchanged. Additions, removals,
project/import changes and evaluated metadata changes still require discovery.
The automatic layout fingerprint excludes body bytes but retains file membership;
bootstrap saves the fingerprint with the newly evaluated body set. Previously
exported layouts must be regenerated to include resource ownership.

Dependency resources stay in their own project actions, rather than being staged
again into each consuming project's payload. Structural dependency files remain
available. Restore's sandbox denies regular-file resource-body reads using suffix rules with
explicit exceptions for declared structural inputs, including XML imports. This
avoids macOS's compiled sandbox size limit on large resource sets. Directory
enumeration remains permitted even when a project directory ends in a resource
suffix, such as OrchardCore.Liquid. A full-graph preflight exposed this case;
the failed restore is excluded from timing results, and the corrected rule
passes isolated restore in 3.198 seconds. Timeout failures now retain restore
subprocess output for diagnosis.

## Validation

- Full local checks: 63 workflow tests (one Linux-only skip), 33 preparation
  tests, five style tests and warning-free builds.
- A 6,000-source / 4,000-resource sandbox control denies body reads while allowing
  declared structural inputs and package files. The actual Orchard profile also
  compiles at the full worker scratch path.
- Binding parity checks cover linked resources, dependency resource omission,
  retained structural files, stale declarations and protected-role aliases.
- Native four-project graph: a linked XML resource edit takes 2.108 seconds,
  executes one binding/compilation and zero discovery, and embeds the new bytes.
  The previous probe took 6.502 seconds with two compilations and discovery.
  Resource additions/removals refresh discovery and change the embedded output;
  local/shared imports invalidate the expected projects; no-op takes 0.606 seconds.

## Orchard workflow qualification

The 202-project Orchard Release/Production graph uses the same pinned revision
and loopback HTTP-cache setup as the prior
[discovery/binding optimization](discovery-binding-performance.md). All reported
workflow runs were accepted. Each producer/edit/recovery time is one sample;
no-op is the median of three samples.

| Measurement | Previous | Resource-body split |
| --- | ---: | ---: |
| CSS edit, complete workflow | 338.668 s | **53.021 s** |
| Discovery executions on CSS edit | 1 (150.306 s) | **0** |
| Locked restore executions on CSS edit | 1 | **0** |
| Binding actions on CSS edit | 4 | **1** |
| Compilations on CSS edit | 4 | **1** |
| Fresh remote recovery | 35.923 s | 37.809 s |
| No-op median | 6.441 s | 6.754 s |

CSS edits are **84.3% faster (6.39x)** than the preceding implementation.
The Razor edit completes in **49.562 seconds**, also with one binding, one
compilation, zero discovery and zero restore. Only `OrchardCore.Setup` binds and
compiles in either case; the other 201 project actions remain reusable. A matching
Razor timing was not taken at the immediately preceding implementation.

Both runtime checks return HTTP 200 and serve the new CSS/Razor marker alongside
the prior C# header and resource markers. After deleting the producer's Bazel
output and generated workspace trees, fresh recovery hits all 202 bindings,
202 compilations, 287 package extractions, restore, discovery and runtime
composition. It performs no compilation and downloads no extracted package
files. All **3,457 application files** match byte for byte, and the recovered app
runs with both source checkouts unavailable. All three no-ops execute no restore,
discovery, binding, compilation or package extraction.

The producer took 840.462 seconds with 202 compilations and 287 extractions.
Completed benchmark storage was reclaimed during that run, so its timing is
not a controlled cold-performance comparison. CSS/Razor timing ran without
concurrent cleanup or builds. The initial restore-timeout attempt is excluded.

## Remaining cost and scope

The CSS Bazel phase takes 23.678 seconds within the 53.021-second complete
workflow. Its action-processing samples are 0.766 seconds for binding,
5.016 seconds for compilation and 10.753 seconds for runtime composition.
Razor is similar: 22.071 seconds in Bazel, with 0.345 / 4.676 / 10.214 seconds
for those three actions. Action-processing samples are not whole-workflow totals.

Each edit publishes 3,186 cache objects and approximately **648.7 MB**, with zero
publication failures. Runtime composition and the controller/publication work
outside the Bazel phase are the next costs to profile. Discovery is no longer
on this resource-edit path. Fresh recovery and no-op timings are broadly similar
to the preceding samples; these are not WAN or remote-execution measurements.
Raw MSBuild was not remeasured, and no parity claim follows.

Counts, exact project names, timings, native controls and comparison samples are
in [resource-body-evidence.json](resource-body-evidence.json). Implementation:
`80c738f` plus the regular-file sandbox correction `c48d728`. No CI, push or
merge was performed.

## Reproduction

Run `nix develop -c bash scripts/check-dotnet.sh` for local validation and
`tests/remote_workers/project_input_probe.py --help` for the native resource,
namespace and import invalidation probe. The native accepted report is retained
at `/private/tmp/resource-body-native-4/report.json`.

The full request and harness are
`/private/tmp/orchard-pilot-evidence/resource-producer-request.json` and
`/private/tmp/orchard-pilot-evidence/run_resource_benchmark.py`. They use the
combined-qualification build flags, a layout regenerated with
`owned-export-layout`, and `RULES_MSBUILD_TRACE=1`. The harness changes Setup's
`wwwroot/Styles/setup.min.css` and `Views/Setup/Index.cshtml` sequentially, checks
live output, removes producer state, recovers with uploads disabled, checks all
application hashes, hides the source checkouts for runtime acceptance, and runs
three no-ops. Reports, action records, Bazel profiles and runtime logs are in
`/private/tmp/orchard-resource-benchmark`.
