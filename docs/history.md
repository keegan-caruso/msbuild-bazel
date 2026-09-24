# Historical implementation and experiments

The supported interface is `msbuild/defs.bzl` and `tools/ExplicitBuild`. Earlier
versions discovered whole MSBuild graphs, exported generated Bazel declarations,
staged preparation bundles and replayed build results through a native cache.
Those implementations and their dependent tests were removed. Their reports are
not current usage instructions or current compatibility claims.

The active documentation tree now keeps user guides, current qualification and
the evidence those claims cite. Superseded designs, experiments and old roadmap
matrices remain available in Git history:

- [Complete pre-cleanup documentation](https://github.com/keegan-caruso/msbuild-bazel/tree/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs).
- [Old implementation chronology](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/implementation-history.md).
- [Old roadmap and work-package definitions](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/historical-roadmap.md).
- [Retired code and validation details](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/legacy-implementation-removal.md).

For old commands, check out their recorded implementation revision. Revision
`067cd59` retains the removed implementations; `da9648b` also retains their shell
entry points. Documentation-only snapshots do not restore deleted executables.
Do not combine benchmark numbers across implementations, tool versions or cache
states, or count an old accepted slice as qualification of a new one.
