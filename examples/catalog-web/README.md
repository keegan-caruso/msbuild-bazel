# Package-backed web app

Five projects: domain, JSON-backed data, services, Razor/API web app, and executable tests. Central versions cover `Newtonsoft.Json`, `Humanizer`, transitive Options packages, and a packaged analyzer. NuGet resolves only during explicit update; Bazel fetches the committed inventory for offline Restore. `mappings.json` reviews compiler reference boundaries; sync captures SDK-selected references and runtime copies. The downloaded SDK provides the ASP.NET host.

Copy beside a pinned rules checkout (adjust module override if needed):

```sh
cp -R msbuild-bazel/examples/catalog-web my-catalog
cd my-catalog
bazel run //:app -- --urls http://127.0.0.1:5080
bazel test //:tests //:web_test //:published_test
bazel run //:published_app -- --smoke
```

Visit `/Index` or `/api/products`. `--smoke` starts an ephemeral loopback server, checks API/page/static endpoints, and exits.

After changing `Directory.Packages.props`, framework, or SDK selection:

```sh
bazel run //:update_packages
bazel run //:sync
bazel test //:tests //:web_test //:published_test
```

Commit `packages.lock.json` files, `nuget.lock.json`, generated graph files, and `MODULE.bazel.lock`. Builds never resolve missing packages. Build servers can run `bazel run //:sync -- --check`; `update_packages -- --check` repeats online resolution. Body and API edits build normally. See [configuration](../../docs/api.md) and [qualified scope](../../docs/support.md).
