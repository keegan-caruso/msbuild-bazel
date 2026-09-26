# Documentation

Start with the [runnable example](../examples/hello/README.md), then the
[rule API](explicit-bazel-rules.md). [Current support](implementation-plan.md)
separates qualified behavior from the [ordered delivery plan](roadmap.md).

## Use the rules

- [Build inputs and rule API](explicit-bazel-rules.md)
- [Project-to-BUILD synchronization](project-sync.md) and [generated Orchard/Avalonia qualification](project-sync-broader-graphs.md)
- [Configured graphs and private dependencies](configured-graphs.md)
- [Executable, MTP and VSTest tests](bazel-test.md)
- [Linux persistent workers](explicit-linux-workers.md) and [remote execution](remote-execution.md)
- [Build task tools](explicit-tool-bindings.md), [generation](explicit-generation.md),
  [project analyzers](project-built-analyzers.md) and [target-result items](msbuild-target-items.md)
- [Restore inputs](explicit-restore-inputs.md), [package trees](explicit-package-borrowing.md)
  and [NuGet metadata](orchard-package-semantics.md)
- [Framework/tool roles](framework-tool-roles.md), [friend assemblies](internals-visible-to.md)
  and [runtime assembly/host primitives](runtime-primitives.md)

## Develop and operate

- [Setup and version selection](development.md)
- [Apple containers](apple-container-runbook.md) and [HTTP action cache](native-cache-service.md)
- [Platform limits](platform-validation-scope.md) and [manual CI](ci-scope.md)
- [Contributing](../CONTRIBUTING.md), [security reporting](../SECURITY.md),
  [agent instructions](../AGENTS.md) and [publication readiness](publication-readiness.md)

## Qualification and measurements

Start with [performance versus raw MSBuild](performance.md) for the consolidated
results. The reports below provide detailed evidence and reproduction steps.

| Workload | Current report and reproduction |
| --- | --- |
| Orchard | [Compatibility](orchard-explicit-compatibility.md), [performance](orchard-explicit-performance.md), [paths](orchard-stable-worker-paths.md), [packages](orchard-package-qualification.md) |
| NBGV | [Version parity and remaining limits](nbgv-parity.md) |
| Avalonia | [XAML graph](avalonia-xaml-subset.md), [HTTP recovery](avalonia-http-cache.md), [remote execution](avalonia-remote-execution.md), [expanded suites and Desktop](avalonia-expanded.md), [edit and Headless controls](avalonia-correctness.md) |
| ASP.NET Core | [Integration](aspnetcore-integration.md), [larger graph](aspnetcore-large-graph.md), [cache profile](aspnetcore-cache-profile.md) |
| dotnet/runtime | [Source-only host](runtime-source-host.md), [Pipelines suite](runtime-pipelines.md), [cold/recovery timing](runtime-cold-timing.md), [leaf edit](runtime-leaf-timing.md), [workflow](runtime-workflow.md), [JIT boundary](runtime-jit-bootstrap.md) |
| Runner overhead | [Cold profile](explicit-cold-profile.md), [staging](worker-staging.md), [evaluation](project-evaluation-removal.md) |
| Version/cache controls | [8.8 qualification](bazel-8.8-upgrade.md), [cache diagnosis](runtime-cache-diagnosis.md), [remote execution](remote-execution.md) |

Reports qualify their exact revisions and slices; they are not blanket support
claims. Evidence JSON stays beside the report that cites it. Temporary paths are
provenance, not public artifact downloads.

Older implementations, superseded designs and intermediate experiments are linked
from [history](history.md), rather than duplicated in this tree. See the
[issue review](issue-review-2026-09-23.md) for tracker dispositions.

- [Everyday synchronization changes](project-sync-mutations.md) — edit, stale check, repair and cache reversion.
