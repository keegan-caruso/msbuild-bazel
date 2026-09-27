# App on a source-built runtime

This ordinary `net10.0` console app is the acceptance example for the
[source-runtime goal](../../docs/runtime-application.md). Its BUILD file belongs
in the prepared workspace as `app/`, alongside the declared `//runtime:app_host`.
It is not a standalone workspace.

The app exercises JSON serialization, asynchronous stream reading, gzip and
SHA-256. `--describe-runtime` also prints hashes of observed managed assemblies,
native mappings and the running dotnet executable on Linux.

The application still compiles with the SDK targeting pack. Its `runtime_host`
selects the source-built runtime for execution. Building a source SDK or targeting
pack is outside this example.
