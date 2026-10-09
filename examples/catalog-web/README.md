# Package-backed web app

Five projects: domain, JSON-backed data, services, a Razor/API web app and executable
tests. Newtonsoft.Json and Humanizer.Core are pinned and acquired by Bazel;
Restore consumes their declared closed inventory. `mappings.json` reviews these
managed compiler reference boundaries; sync captures the SDK-selected references
and runtime copies. The downloaded SDK supplies the
ASP.NET execution host.

Copy beside a pinned rules checkout, adjusting the module override if needed:

```sh
cp -R msbuild-bazel/examples/catalog-web my-catalog
cd my-catalog
bazel run //:app -- --urls http://127.0.0.1:5080
bazel test //:tests //:web_test //:published_test
bazel run //:published_app -- --smoke
```

Visit `/Index` or `/api/products`. `--smoke` starts an ephemeral loopback server,
checks the API/page and published static endpoints, then exits.

Commit `MODULE.bazel.lock`. Run `bazel run //:sync` after project, package or input
membership changes, and `bazel run //:sync -- --check` on build servers. Method-body
and API edits build normally. Package version changes require updating both archive
hashes/content hashes and the closed package declarations; sync does not fetch
undeclared packages. See [configuration](../../docs/api.md) and
[qualified scope](../../docs/support.md).
