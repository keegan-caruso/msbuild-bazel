# App on a source-built runtime

Build the pinned Linux ARM64 .NET 10 runtime and run an ordinary app on it.
The downloaded SDK compiles the graph; the source-built host, CoreLib and BCL
execute the app. [Pins](source.json) identify the source and bootstrap SDK.

On Apple silicon, install Apple Container and provide 32 GiB free space:

```sh
container system start
python3 scripts/setup-source-runtime.py "$HOME/source-runtime"
bash "$HOME/source-runtime/run.sh" --describe-runtime --verify-product
```

Run from the rules checkout with Git, Python and download access. Setup builds the
[native environment](../../containers/runtime-demo.Dockerfile), creates an owned
worker, runs package update/check and graph sync/check, then builds and verifies
the app and runtime archive. Native Ubuntu 22.04 ARM64 can run the same command
with those dependencies, an 8 GiB memory budget (RAM plus swap), and nested
user/mount namespaces available.

Resume interrupted setup with the same command plus `--resume`. Retain the setup
directory; Linux also retains a dependency on this rules checkout. Reports and
timings stay under the setup directory.

Pass `--cache-url=http://CACHE:8080` to reuse Bazel actions and MSBuild project
snapshots. The endpoint must be reachable from the build worker.

The declared `//:runtime_package` output is exported as
`runtime-linux-arm64.tar.gz` in that directory. It is an unsigned IL developer
runtime with source provenance and upstream licenses. Qualification and platform
limits are in [support](../../docs/support.md).

For compilation with a source-built **SDK**, use the separate
[quick-start scenario](../quickstart/README.md#source-built-sdk).
The reusable declarations are [runtime selection](../../docs/api.md#build-and-artifacts).
