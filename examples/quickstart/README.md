# Quickstart

Requires Bazelisk and OS .NET prerequisites. Bazel supplies the SDK from `global.json`.
Copy beside a rules checkout (or adjust `MODULE.bazel`'s `../msbuild-bazel` path):

```sh
cp -R msbuild-bazel/examples/quickstart my-app
cd my-app
bazel run //:app
bazel test //:tests
bazel run //:sync -- --check
```

For a new app, declare `msbuild_sync` in the root BUILD file, run it, then add the
load and graph/run/test targets shown in [BUILD.bazel](BUILD.bazel). Commit both
generated graph files. Body edits build normally; rerun sync after project/import,
source-list, package or configuration changes. Build servers use `--check`.

See [API](../../docs/api.md) for packages, tools, configuration and test protocols;
check [support limits](../../docs/support.md) before adopting custom build logic.
