# Quickstart

Requires Bazelisk and normal OS .NET prerequisites. Bazel downloads the pinned SDK.
Copy beside a checkout of the rules:

```sh
cp -R msbuild-bazel/examples/quickstart my-app
cd my-app
bazel run //:app
bazel test //:tests
bazel run //:sync -- --check
```

`MODULE.bazel` uses `../msbuild-bazel`; adjust that path for your checkout. The SDK
comes from `global.json`. Generated graph declarations are committed.

For a new app, initially declare only `msbuild_sync`, run it, then add the generated
load and graph/run/test targets shown in `BUILD.bazel`. Body edits build normally.
After project/props/targets, source-list, package or configuration changes, rerun
sync and commit both generated files. Build servers use `--check`.

Use sync's `configuration`, `framework`, closed `package_lock`, and reviewed
`mappings` as needed. Package targets require `package_build = True` and explicit
extra inputs. Multiple frameworks need explicit run/test framework selection.
See [graph API](../../docs/graph-workflow.md), [sync](../../docs/project-sync.md),
[tests](../../docs/bazel-test.md) and [limits](../../docs/implementation-plan.md).
