# Adoption, upgrades and distribution

The supported entry point is the [SDK-and-sync quickstart](../examples/quickstart/README.md):
normal `.csproj` files, a tracked SDK pin, an authored sync target and committed
generated declarations. Builds and tests use the explicit graph; synchronization
is a deliberate local operation when evaluated inputs change.

## Current distribution and compatibility

Use a reviewed **source commit** through a pinned checkout with `local_path_override`,
or `git_override` with a full commit SHA. The module's `0.0.0` is a source-workflow
placeholder, not a published version. Neither `main` nor an unpinned branch is a
reproducibility boundary. An external application needs Bazelisk and OS sandbox/runtime
libraries; the SDK and build tools come from declared Bazel inputs.

The current baselines are SDK **10.0.400**, Bazel **8.8.0 / 9.2.0**, with this
quickstart's execution and independent-cache evidence on **Linux ARM64**. The SDK
catalog also declares 10.0.401; catalog presence is distinct from qualifying every
application on that pin. See [SDK selection](development.md) for supported
`global.json` policies and [platform scope](platform-validation-scope.md).

The public macros/providers, sync mapping format and generated output remain
experimental. A source revision pins their implementations together; no cross-version
runner or generated-file compatibility is promised. Keep the runner, generator,
Starlark rules and generated declarations from a compatible source revision. A
cached result from an older rules revision is reusable only if Bazel's declared
action identity still matches; do not force compatibility by dropping tool inputs.

## Upgrade one boundary at a time

1. Start from a clean application checkout and record the old rules commit, SDK,
   Bazel pin and existing build/test result.
2. Change the rules source pin. Read its migration notes and reviewed diff. Keep
   SDK/Bazel fixed initially so an error has a clear cause.
3. Run `bazel run //:sync`, inspect the generated diff, then
   `bazel run //:sync -- --check`. Review custom import/task contracts explicitly;
   do not update their hashes just to suppress drift errors.
4. Run the application's builds/tests, a representative body edit and API edit,
   and a source-only consumer against the build-server cache. Cache hits alone do
   not prove runtime correctness: force at least the relevant tests to execute.
5. Commit the source pin, mappings, generated declarations and module lock together.
   If changing SDK or Bazel too, repeat the controls as a separate change. Roll back
   the entire set to return to the previous configuration.

Package upgrades are separate declared inputs: update the archive identity/digest
and explicit mappings, sync, and test the affected dependency paths. Unsupported
conditions, task behavior or framework selections should stop with a diagnostic,
not silently fall back to a machine's installed tools.

## Proposed release path — not published

| Phase | Proposed contract | Gate before publishing |
| --- | --- | --- |
| Source snapshots (current) | Exact Git revision supplies rules, runner and generator together | Clean SDK-only example, generated drift check and independent consumer |
| Versioned runner/generator packages | Per-platform immutable archives with digests, a versioned runner protocol and explicit matching rules metadata; retain source bootstrap | Parity with source bootstrap, platform/runtime closure, tamper rejection, upgrade/rollback tests and release automation review |
| Bazel Central Registry module | Versioned source archives, integrity metadata, compatibility level and minimal external example | Stable-enough API policy, registry tests on supported platforms/Bazel versions, provenance/license review and published compatible tool packages or source fallback |

Before a first versioned release, define which attributes/providers and mapping
schema are stable, and how breaking changes increment the module compatibility
level. Record migration notes and support ranges per release. Do not infer that
semver, an archive checksum or a registry entry alone proves remote-cache or
cross-platform correctness. This proposal creates no release, tag or BCR submission.

## Qualification

The [quickstart evidence](adoption-evidence.json) records actual checked-in-example
commands, supported Bazel versions, dependency-test failure/repair, relocation,
cache hits and fresh execution. Sources are copied to independent workspaces;
no SDK installation, NuGet cache or producer output mount fills undeclared inputs.
The larger [generated graph qualifications](project-sync-broader-graphs.md) remain
separate evidence. The small example does not qualify every application, workload,
OS condition, test adapter or source-built runtime.


Both Bazel 8.8.0 and 9.2.0 passed the committed-example app, test, no-op,
body-edit failure and cache repair controls. The independent consumer recovered
all six build/tool actions (sync bootstrap, runner, SDK runtime and three
assemblies), recovered the cached test, matched every recorded reference/runtime
file and passed forced test execution. Both containers hid the image SDK; the
producer was stopped and neither container mounted the other's filesystem.
The driver counts distinct test targets because Bazel can log multiple spawns for
one test.

Reproduce after copying the example as described in its README:

```sh
python3 tests/project_sync/quickstart.py APP ABSENT_BASE SEED.json --cache CACHE_URL
# On a source-only consumer, with the producer stopped:
python3 tests/project_sync/quickstart.py APP ABSENT_BASE CONSUMER.json \
  --cache CACHE_URL --expect SEED.json
```

Use `USE_BAZEL_VERSION=8.8.0` to repeat on the other supported baseline. This is an
optional qualification driver; the application workflow itself uses only the
README's Bazel commands. Repository checks parse generated Starlark without
reformatting generator-owned bytes; `sync --check` verifies its exact contents.
