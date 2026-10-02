# Historical implementations

The graph workflow is now the only build backend. The previous per-project
compiler/worker, generator, public facades and their implementation-specific tests
were removed. Shared artifact acquisition and launch utilities remain in
`tools/ArtifactTools`.

The [complete pre-cutover tree at `7e22cd6`](https://github.com/keegan-caruso/msbuild-bazel/tree/7e22cd67609f6ae5e1606fcae9dcf6e578c2db3b)
contains that backend, its reports, and the full graph qualification chronology:

- [Graph migration/API development](https://github.com/keegan-caruso/msbuild-bazel/blob/7e22cd67609f6ae5e1606fcae9dcf6e578c2db3b/docs/project-cache-migration.md)
- [Graph qualification checkpoints](https://github.com/keegan-caruso/msbuild-bazel/blob/7e22cd67609f6ae5e1606fcae9dcf6e578c2db3b/docs/graph-cache-plan.md)
- [Full performance evidence](https://github.com/keegan-caruso/msbuild-bazel/blob/7e22cd67609f6ae5e1606fcae9dcf6e578c2db3b/docs/performance.md)
- [Retired per-project docs and evidence](https://github.com/keegan-caruso/msbuild-bazel/tree/7e22cd67609f6ae5e1606fcae9dcf6e578c2db3b/docs)

Still older discovery/replay implementations are preserved at revisions `067cd59`
and `da9648b` (including their shell entrypoints). Their
[earlier documentation snapshot](https://github.com/keegan-caruso/msbuild-bazel/tree/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs)
is historical, not current instructions.

Check out the recorded implementation revision to reproduce old commands.
Do not combine results across backends, tool versions, graph scope or cache states.
