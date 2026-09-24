# Issue review — 2026-09-23

Reviewed all 55 previously open GitHub issues against the current explicit rules,
qualification reports and remaining limits. Original imported acceptance criteria
remain in each issue for traceability. GitHub and Linear use matching dispositions.

## Closed or consolidated

| GitHub | Linear | Disposition | Scope |
| --- | --- | --- | --- |
| [#17](https://github.com/keegan-caruso/msbuild-bazel/issues/17) | RUL-22 | Completed | Independent-worker remote cache qualification |
| [#20](https://github.com/keegan-caruso/msbuild-bazel/issues/20) | RUL-25 | Completed | Qualify selected dotnet/runtime managed and native slices |
| [#24](https://github.com/keegan-caruso/msbuild-bazel/issues/24) | RUL-43 | Completed | Declare source-built MSBuild task producers and dependencies |
| [#33](https://github.com/keegan-caruso/msbuild-bazel/issues/33) | RUL-52 | Retired | Retire discovery/export preparation reuse |
| [#34](https://github.com/keegan-caruso/msbuild-bazel/issues/34) | RUL-53 | Completed | Separate compiler references from runtime and test inputs |
| [#41](https://github.com/keegan-caruso/msbuild-bazel/issues/41) | RUL-60 | Retired | Retire the legacy native-cache worker descriptor |
| [#42](https://github.com/keegan-caruso/msbuild-bazel/issues/42) | RUL-61 | Completed | Recover and execute outputs on an independent cache consumer |
| [#46](https://github.com/keegan-caruso/msbuild-bazel/issues/46) | RUL-65 | Completed | Qualify a selected dotnet/runtime managed subtree |
| [#47](https://github.com/keegan-caruso/msbuild-bazel/issues/47) | RUL-66 | Completed | Qualify selected source-built runtime native products |
| [#51](https://github.com/keegan-caruso/msbuild-bazel/issues/51) | RUL-71 | Duplicate → [#54](https://github.com/keegan-caruso/msbuild-bazel/issues/54) | Consolidate macOS x64 qualification |
| [#52](https://github.com/keegan-caruso/msbuild-bazel/issues/52) | RUL-72 | Retired | Retire generated-graph Linux ARM64 acceptance |
| [#53](https://github.com/keegan-caruso/msbuild-bazel/issues/53) | RUL-73 | Duplicate → [#56](https://github.com/keegan-caruso/msbuild-bazel/issues/56) | Consolidate Linux x64 qualification |
| [#59](https://github.com/keegan-caruso/msbuild-bazel/issues/59) | RUL-84 | Duplicate → [#61](https://github.com/keegan-caruso/msbuild-bazel/issues/61) | Consolidate Windows ARM64 qualification |
| [#60](https://github.com/keegan-caruso/msbuild-bazel/issues/60) | RUL-85 | Duplicate → [#62](https://github.com/keegan-caruso/msbuild-bazel/issues/62) | Consolidate Windows x64 qualification |

Seven items are complete for their recorded slices, three implementation contracts
were retired, and four duplicate platform tickets were consolidated. Canonical
platform tickets retain their configured-input, mutation and recovery requirements.

## Remaining work

Forty-one existing issues remain open. Added [#74](https://github.com/keegan-caruso/msbuild-bazel/issues/74)
(RUL-95) for the first authored CoreCLR/JIT test bootstrap, bringing the open GitHub
count to **42** at this review. The [roadmap](roadmap.md) orders the next work.

Keep these boundaries explicit:

- Selected runtime managed/native tests pass; full CoreCLR/JIT support is not qualified.
- Local and independent-cache task producers pass; arbitrary build lifecycles remain open.
- Remote execution passes a two-project synthetic; richer closures and real graphs remain open.
- NBGV parity fixtures pass; production Git-context capture is incomplete.
- Serilog, Spectre and ASP.NET source-path-dependent tests still have known failures.
- Coverage, Pack, Publish, AOT and untested platforms remain open.
- Source-publication preparation does not complete runner or BCR distribution.

Also aligned Linear RUL-7, RUL-8 and RUL-9 with the already-closed GitHub #5, #6
and #7. Those are historical preparation milestones, not new qualification claims.

## Documentation policy

Removed 328 superseded documentation and evidence files. Current guides and the
evidence they cite remain. Fixed-revision [history links](history.md) preserve the
old reports without presenting retired commands as current instructions.

This review did not run CI, change repository visibility, or publish a release.
