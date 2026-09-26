# Incremental compilation at reference boundaries

For `A → B → C`, a changed C reference requires B to compile. If B emits the same
reference assembly, A can reuse its compilation **provided C is not also an input
to A's compiler**. Bazel already makes this distinction through artifact inputs.
The default SDK-style transitive graph gives A both B and C, so that default does
not provide this cutoff. Do not remove C merely because today's source appears
not to use it.

## Declaring the boundary

Libraries can opt out of implicit transitive project references in their project
or imported props:

```xml
<PropertyGroup>
  <DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences>
</PropertyGroup>
```

`msbuild_sync` now reads this evaluated property for each target framework and
emits `transitive_compile_references = False`. Previously it always defaulted to
`True`, losing the project's choice. An explicit `transitiveCompileReferences`
mapping overrides inference; `null` resets an inherited mapping to inference.
Authored rules can set the attribute directly. Alternatively, an explicitly
private B→C dependency prevents C from being exported to A's compiler.

This follows the SDK's [DisableTransitiveProjectReferences contract](https://learn.microsoft.com/en-us/dotnet/core/project-sdk/msbuild-props#disabletransitiveprojectreferences).
If A directly uses C, or needs a C type exposed by B, declare A→C explicitly.
Missing references remain compiler errors. Runtime implementations stay
transitive: changed C bodies still invalidate dependent tests and runtime layouts.
Direct-only executable/test compilation remains unsupported because their runtime
manifest generation consumes transitive reference metadata; sync reports that
boundary before replacing generated output.

## Measured matrix

Linux ARM64, SDK 10.0.400, Release/net10.0, Bazel 8.8.0 and 9.2.0. One 6-CPU,
10-GiB producer VM, two build slots/workers, 4096-MB retained-worker budget; a
separate 1-GiB HTTP-cache VM was available. No concurrent build VM. Bootstrap and
restore were excluded from edit samples. Raw MSBuild used the same source graphs
and two build slots. Build-system order alternated over three repetitions.

The matrix covers one A or eight A consumers sharing B→C, plus an unrelated
library, in default-transitive, private-dependency and direct-reference modes.
Each Bazel version passed 54 edit samples and every cache-reversion check.

| C edit | Reference bytes changed | Default transitive compilation | Explicit boundary compilation |
| --- | --- | --- | --- |
| Method body | None | C | C |
| Added public member unused by B | C | C, B, all A | C, B |
| Public constant copied into B and A constants | C, B, A0 | C, B, all A | C, B, all A |

Reference hashes sample C, B and representative consumer A0. Raw MSBuild
produced the same reference-change pattern. The unrelated library
never compiled during edits; reverting each edit executed zero Bazel compilation
actions. Counts come from execution logs, not elapsed-time inference.

Eight-consumer public-addition medians (three samples, seconds):

| Bazel | Reference mode | Bazel median [range] | Raw median [range] | Compilations |
| --- | --- | --- | --- | ---: |
| 9.2.0 | Default transitive | 0.850 [0.814–0.931] | 0.583 [0.527–0.895] | 10 |
| 9.2.0 | Private B→C | 0.270 [0.265–0.285] | 0.494 [0.463–0.541] | 2 |
| 9.2.0 | Direct A references | 0.269 [0.268–0.278] | 0.505 [0.444–0.529] | 2 |
| 8.8.0 | Default transitive | 0.984 [0.874–1.020] | 0.590 [0.529–0.904] | 10 |
| 8.8.0 | Private B→C | 0.307 [0.292–0.316] | 0.473 [0.428–0.545] | 2 |
| 8.8.0 | Direct A references | 0.284 [0.262–0.324] | 0.532 [0.447–0.559] | 2 |

A further Bazel 9 control forced transitive inputs on the same opted-out projects,
reproducing the old generator's input mode: 1.012 s median [0.898–1.771], ten
compilations, versus 0.269 s and two after inference. This is a mapping control,
not a run of an older binary. Small samples and worker warm-up introduce variation;
the removed compilations are stronger evidence than a generalized speedup claim.

## Correctness and cache controls

Both Bazel versions also passed:

- Direct use of undeclared C fails with CS0103; a C type exposed through B fails
  with CS0012. Raw MSBuild agrees. Adding A→C repairs both; restoring the original
  graph reproduces identical generated declarations.
- A C body edit changes executable behavior: only C recompiles, but the dependent
  executable test reruns and fails. Reverting recovers its passing cached result.
- Framework-conditioned imported props, mapping precedence/null reset, stale
  `--check` output preservation, and early executable-boundary diagnostics pass
  the ProjectSync unit suite.

Independent recovery results and exact samples are recorded in
[the evidence](reference-invalidation-evidence.json). Recovery uses a second
container with the producer stopped, a different source path, an empty output
base, no local disk cache, uploads disabled and the installed SDK hidden. The
reference DLLs and runtime payloads must match the seed hashes, every build/test
action must hit HTTP cache, and forced test execution must pass without compiling.
The fixture fixes action/test `PATH` to `/usr/bin:/bin`: Bazel 8 otherwise
inherited a workspace-specific path, which preserved build hits but missed the
relocated test cache. Both versions were reseeded after fixing that environment.
Compiler response files are auxiliary execution files, not cached output payloads;
the hash oracle excludes them. An initial oracle incorrectly included those files;
all 365 payload hashes already matched, and the corrected check was rerun from a
fresh output base.

## Reproduce

With the pinned Linux tool environment (`RULES_MSBUILD_BAZEL` and
`RULES_MSBUILD_DOTNET_ROOT`), use a new output directory for each invocation:

```sh
python3 tests/project_sync/reference_invalidation.py /tmp/reference-9
USE_BAZEL_VERSION=8.8.0 python3 tests/project_sync/reference_invalidation.py /tmp/reference-8
python3 tests/project_sync/reference_invalidation.py /tmp/reference-control \
  --modes direct --widths 8 --force-transitive
python3 tests/project_sync/reference_boundary_controls.py /tmp/reference-seed \
  --cache "$CACHE_URL"
# In a separate source-only container, after stopping the producer:
python3 tests/project_sync/reference_boundary_controls.py /tmp/reference-consumer \
  --cache "$CACHE_URL" --expect /evidence/seed-results.json
```

Repeat the seed/recovery pair with `USE_BAZEL_VERSION=8.8.0`. Copy only tracked
rule sources and the seed's results.json into the consumer, not its outputs or
local caches. The SDK is acquired through the declared Bazel toolchain.

## Remaining scope

This proves a library reference boundary and fixes synchronization of an explicit
SDK setting. It does not automatically prune ordinary transitive graphs, measure
remote execution, qualify direct-only binaries, or improve the recorded 202-project
Orchard API timing. Step 9 still needs representative upstream API edits and
profiling of the expensive cases, including edits that genuinely propagate through
many reference assemblies. Keep those measurements separate from this synthetic.
