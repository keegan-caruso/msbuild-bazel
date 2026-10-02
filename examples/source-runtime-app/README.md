# App on a source-built runtime

Copy into a prepared workspace with `//runtime:app_host`; this is not standalone.
The graph compiles with the declared SDK; `runtime_host` selects the source-produced
execution layout. Run with `--strategy=MSBuildGraph=worker --worker_sandboxing`.
`--describe-runtime` prints loaded component hashes on Linux.
See [runtime selection](../../docs/api.md#build-and-artifacts) and [qualified scope](../../docs/support.md).
