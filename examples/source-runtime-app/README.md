# App on a source-built runtime

Merge [BUILD.bazel](BUILD.bazel)'s declarations and copy the project/contract files
into the root of a prepared workspace exporting `//runtime:app_host`. A declared
SDK compiles the graph, while `runtime_host` selects the
source-produced `dotnet`/`corerun` execution layout independently.

Run `bazel run //:app --strategy=MSBuildGraph=worker --worker_sandboxing` in the
prepared workspace. Append `-- --describe-runtime` to print loaded component hashes
on Linux. This example is not standalone.
For compilation with a source-built **SDK**, use the separate
[quick-start scenario](../quickstart/README.md#source-built-sdk).
See [runtime selection](../../docs/api.md#build-and-artifacts) and [qualified scope](../../docs/support.md).
