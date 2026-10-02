# App on a source-built runtime

Copy this app into a prepared workspace alongside `//runtime:app_host`; it is not
a standalone workspace. Its graph compiles with the declared SDK targeting pack,
then `runtime_host` selects the source-produced execution layout.

The app exercises JSON, async streams, gzip and SHA-256. `--describe-runtime`
prints observed managed/native component hashes on Linux. See
[runtime qualification](../../docs/runtime-qualification.md) for the producer
contracts and SDK-absent execution controls. Building a source SDK is separate.
