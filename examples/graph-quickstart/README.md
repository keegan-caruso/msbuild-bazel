# Graph-mode quickstart

This opt-in workflow shares one MSBuild graph build and exposes separate app/test
runtime outputs. You need Bazelisk and the normal host prerequisites from
[development](../../docs/development.md); Bazel supplies the SDK.

Copy this example beside a pinned checkout of the rules:

```sh
cp -R msbuild-bazel/examples/graph-quickstart my-app
cd my-app
bazel run //:app
bazel test //:tests
bazel run //:sync -- --check
```

`MODULE.bazel` points to `../msbuild-bazel`. The generated declarations are
committed. For a new workspace, declare only `msbuild_sync`, run it once, then
add the generated load and run/test declarations shown in `BUILD.bazel`.

Edit source bodies and build/test normally. After changing project files, props,
sources lists, configuration or packages, run `bazel run //:sync` and commit the
result. Build servers use `bazel run //:sync -- --check` without rewriting files.

Select `configuration = "Debug"` or `framework = "net10.0"` on the sync target.
Without a framework selection, multi-targeted projects generate each framework;
run/test targets then require an explicit `framework`.

For NuGet, pass the existing `msbuild_package_lock` target as `package_lock` on
sync. The generated graph consumes its original, hash-verified archives and
restores offline. The lock must include transitive dependencies. Managed package
assemblies are supported. Set `package_build = True` to evaluate package
build/content assets through offline Restore in a disposable copy. Declare extra
task reads in `package_inputs`; authored custom tasks still require contracts.
Graph tests also support `test_protocol = "mtp"` or `"vstest"` with the existing
[runner options](../../docs/bazel-test.md). See
[graph migration](../../docs/project-cache-migration.md) for measured scope.

The app and executable test select projects by path, not DLL output paths. Tests
consume only their selected runtime directory. An unrelated graph edit can keep
a test cached; changing a runtime dependency reruns it.

The graph backend remains opt-in. Stable Bazel execution paths and large-project
parity are still open. This example does not establish remote execution or the
standalone runner's incremental timings inside ordinary Bazel sandboxes.
