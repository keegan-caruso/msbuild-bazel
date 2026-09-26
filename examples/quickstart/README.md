# A .NET app built with Bazel

This example has a library, an application and an executable test, with no NuGet
packages. Its generated project graph is committed. Bazel acquires the SDK named
in `global.json`, builds the runner and supplies the bundled application runtime.
You need **Bazelisk** (available as `bazel`), Git and the host OS prerequisites;
you do not need to install .NET or run a repository setup/generation script.

## Build and test

On qualified Linux ARM64, provide `/usr/bin/bwrap` (bubblewrap), enabled user/mount
namespaces, CA certificates and the .NET native libraries. Ubuntu 22.04 uses
`libicu70`, `libssl3` and `zlib1g`. Containers must permit nested namespaces.
See [host requirements and platform scope](https://github.com/keegan-caruso/msbuild-bazel/blob/main/docs/development.md).

Start in a directory where neither destination exists:

```sh
git clone https://github.com/keegan-caruso/msbuild-bazel.git
cp -R msbuild-bazel/examples/quickstart my-app
cd my-app
bazel run //:App_App
bazel test //:Tests_Tests
bazel run //:sync -- --check
```

The app prints `Hello from MSBuild and Bazel`; the test passes. The final command
checks that the committed declarations match the current projects. Normal
`build`, `run` and `test` commands consume those declarations directly.

`MODULE.bazel` uses the adjacent rules source checkout. Record its reviewed Git
commit in your checkout/build-server configuration; a moving `main` is unsuitable
as a reproducibility pin. To use another directory, change `local_path_override`.
There is currently no published runner package or Bazel Central Registry release.

## Files you own

- `global.json` selects SDK **10.0.400**; `.bazelversion` selects **9.2.0**.
- `BUILD.bazel` declares `msbuild_sync` and calls the generated `app_projects()`.
- `sync.json` explicitly identifies the executable test. Exit code zero means pass.
- The `.csproj` files retain normal `ProjectReference` and SDK compilation.
- `projects.generated.bzl` contains explicit sources, configured projects and edges.
  Update it through sync; do not edit or separately format its contents.

Commit these files and the `MODULE.bazel.lock` produced by Bazel in your app repo.
For an existing application, follow [first synchronization](https://github.com/keegan-caruso/msbuild-bazel/blob/main/docs/project-sync.md#app-developer-setup)
before adding the generated load to BUILD.

## The edit loop

Edit source bodies and use `bazel test //:Tests_Tests`. To observe dependency test
invalidation, change the string in `Library/Message.cs`: the test must fail even
though the library's public API is unchanged. Update its expectation in
`Tests/Program.cs` (and the app's check in `App/Program.cs`) to make it pass again.

When you add/remove sources, projects or references, or change evaluated props or
frameworks:

```sh
bazel run //:sync
bazel run //:sync -- --check
bazel test //:Tests_Tests
```

Review and commit the generated diff with the project change. Failed sync preserves
the last valid output. A build server can run `--check` before its build to reject
stale declarations; it must not silently rewrite them.

For cases beyond this example, use explicit mappings for
[packages and test protocols](https://github.com/keegan-caruso/msbuild-bazel/blob/main/docs/project-sync.md#explicit-package-and-test-mappings),
[task tools and custom imports](https://github.com/keegan-caruso/msbuild-bazel/blob/main/docs/project-sync-bindings.md), and
[configured frameworks](https://github.com/keegan-caruso/msbuild-bazel/blob/main/docs/configured-graphs.md). Unknown task behavior
requires a reviewed contract. Sync does not execute restore or arbitrary targets,
guess packages, or expand every OS/property condition.

## Build server and second cache consumer

Use a trusted HTTP action cache reachable from both machines. Set `CACHE_URL` to
its endpoint; use your service's authentication/TLS configuration. Keep credentials
out of committed files. The local cache [runbook](https://github.com/keegan-caruso/msbuild-bazel/blob/main/docs/native-cache-service.md)
is one option; hosting the server is independent of this example.

The producer runs the same checkout and pins. For this first seeding proof, clear
its previous local action outputs so the cache receives executed results:

```sh
bazel clean
bazel run //:sync --remote_cache="$CACHE_URL" -- --check
bazel build //:App_App --remote_cache="$CACHE_URL" --remote_download_outputs=all
bazel test //:Tests_Tests --remote_cache="$CACHE_URL" --remote_download_outputs=all
bazel shutdown
```

On a second machine or container, copy/checkout **source files only**, including
the committed generated file and the same rules commit. Keep the relative layout
(`msbuild-bazel` beside `my-app`) or update the local override. Use a different
absolute path and no producer output mounts. Set `CACHE_URL` there too. With a new
absolute `FRESH_BASE` path that does not yet exist:

```sh
bazel --output_base="$FRESH_BASE" build //:App_App \
  --remote_cache="$CACHE_URL" --remote_upload_local_results=false \
  --disk_cache= --remote_download_outputs=all
bazel --output_base="$FRESH_BASE" test //:Tests_Tests \
  --remote_cache="$CACHE_URL" --remote_upload_local_results=false \
  --disk_cache= --remote_download_outputs=all
bazel --output_base="$FRESH_BASE" run //:sync \
  --remote_cache="$CACHE_URL" --remote_upload_local_results=false --disk_cache= -- --check
```

Build logs should report remote cache hits and the test should be cached. To prove
the recovered test can execute, repeat the test command with
`--nocache_test_results`. Downloads of SDK/repository inputs are separate from
action-cache hits. A source body/API change must still invalidate the affected
builds/tests. This qualifies caching; it does not configure remote execution.

## Upgrades and support

See [adoption and versioning](https://github.com/keegan-caruso/msbuild-bazel/blob/main/docs/adoption.md) for upgrade steps and the
proposed distribution path. The example is package-free and Release/net10.0;
[current support](https://github.com/keegan-caruso/msbuild-bazel/blob/main/docs/implementation-plan.md) describes the broader measured
slices and limits. This is an experimental API, not a stable compatibility promise.
