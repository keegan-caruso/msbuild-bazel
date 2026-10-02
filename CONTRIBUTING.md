# Contributing

Create a focused branch/worktree. Keep rules generic, inputs explicit and MSBuild's
SDK behavior intact. Add small independent controls for behavioral changes; record
the command, outcome and limits in [support](docs/support.md) or [performance](docs/performance.md).
Use [AGENTS.md](AGENTS.md) for repository policy. GitHub CI is manual-only and requires
an explicit maintainer request.

## Checks

```sh
bash scripts/setup.sh
source scripts/env.sh
bash scripts/check.sh
bash scripts/check-dotnet.sh
bash scripts/check-analysis.sh
bash scripts/bazel.sh test //tests/integration:quickstart --test_output=errors
python3 tests/graph_build/acceptance.py /tmp/fresh-graph-acceptance
```

Setup acquires pinned contributor tools. Check shell/Starlark/pins with `check.sh`,
owned .NET formatting/warnings/unit tests with `check-dotnet.sh`, and rule contracts
with `check-analysis.sh`. Use fresh fixture/report directories; documentation-only
changes need link/path checks and `git diff --check`, not builds.
`USE_BAZEL_VERSION=8.8.0` selects the other baseline. Use wrappers and explicit
`RULES_MSBUILD_BAZELISK` / `RULES_MSBUILD_DOTNET_ROOT` overrides instead of PATH changes.
The latter selects contributor tooling, not an application SDK repository.

## Linux qualification on Apple silicon

```sh
bash scripts/build-apple-container-image.sh
export RULES_MSBUILD_CONTAINER_IMAGE="$(cat .cache/apple-container/arm64/image.ref)"
bash scripts/run-apple-container.sh bash -lc '
  bash scripts/check-dotnet.sh &&
  python3 tests/graph_build/acceptance.py /evidence/acceptance
'
```

The disposable runner copies sources from a read-only mount and retains reports in
`artifacts/apple-container/run.*`; it excludes `.git` and build/download caches.
Native integration tests use `rules_bazel_integration_test` with declared fixtures,
private scratch trees outside the checkout (avoiding ancestor MSBuild imports),
and both Bazel baselines. `//tests/integration:workers` covers
body/API edits, failure recovery and Build/Publish parity, with caching enabled and
disabled; acceptance adds it with `--linux-workers`. These trusted nested builds
run outside the outer test sandbox; worker actions still use `--worker_sandboxing`.
Workers require a namespace-enabled Ubuntu ARM64 environment.
`RULES_MSBUILD_TEST_REPOSITORY_CACHE=/absolute/path` optionally shares Bazel’s verified
archive cache across nested tests; it does not supply a host SDK.
Native runtime checks need additional capabilities/prerequisites; follow the relevant
`tests/runtime` driver. This basic runner does not establish those qualifications.

A trusted HTTP AC/CAS service can supply both caches ([configuration](docs/api.md#caching-and-workers)).
For the pinned macOS loopback service: `bash scripts/install-native-cache.sh /absolute/path/bazel-remote`.
It installs a user launch agent on port 9090 with 10 GiB LRU storage; it is not
available while the Mac sleeps. Use authenticated forwarding for other machines.

## Pull requests

Include the problem, change, relevant checks and remaining limits. Bugs need a small
reproducer plus command, revision, SDK/Bazel versions, OS/architecture and expected/
actual results. Review logs before sharing; use [SECURITY.md](SECURITY.md) for vulnerabilities.
Keep SDKs, packages, build products and raw reports out of Git. Contributions are
[MIT licensed](LICENSE); preserve third-party notices.
