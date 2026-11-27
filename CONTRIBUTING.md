# Contributing

Use a focused branch/worktree. Keep rules generic, inputs explicit, and MSBuild SDK behavior intact. For behavioral changes, add small independent controls and record command, outcome, and limits in [support](docs/support.md) or [performance](docs/performance.md). [AGENTS.md](AGENTS.md) is repo policy; GitHub CI is manual and requires explicit maintainer request.

## Checks

```sh
bash scripts/setup.sh
bash scripts/check.sh
bash scripts/check-dotnet.sh
bash scripts/check-analysis.sh
bash scripts/bazel.sh test //tests/integration:quickstart --test_output=errors
python3 tests/graph_build/acceptance.py /tmp/fresh-graph-acceptance
```

Setup acquires pinned contributor tools. Checks cover shell/Starlark/pins, owned .NET formatting/warnings/unit tests, and rule contracts. Use fresh fixture/report directories. Docs-only changes need link/path checks and `git diff --check`. Baseline: Bazel 9.3.3 (`USE_BAZEL_VERSION` overrides `.bazelversion` for experiments; other versions are unqualified). Use wrappers and explicit `RULES_MSBUILD_BAZELISK` / `RULES_MSBUILD_DOTNET_ROOT` overrides (the latter selects contributor tooling, not an application SDK repository).

`scripts/check-dotnet.sh` uses `python3` by default. Set `RULES_MSBUILD_PYTHON` to another Python 3 executable when needed, including `python.exe` on Windows.

## Linux on Apple silicon

```sh
bash scripts/build-apple-container-image.sh
export RULES_MSBUILD_CONTAINER_IMAGE="$(cat .cache/apple-container/arm64/image.ref)"
bash scripts/run-apple-container.sh bash -lc '
  bash scripts/check-dotnet.sh &&
  python3 tests/graph_build/acceptance.py /evidence/acceptance
'
```

The disposable runner copies a read-only source mount and saves reports in `artifacts/apple-container/run.*` (excluding checkout/build/download caches). Native tests use `rules_bazel_integration_test`, private fixtures, and both Bazel pins. `//tests/integration:workers` covers edits, failure recovery, and Build/Publish with caching on/off; acceptance adds it via `--linux-workers`. Trusted nested builds run outside the outer sandbox; workers use `--worker_sandboxing` and require a namespace-enabled Ubuntu ARM64 environment. `RULES_MSBUILD_TEST_REPOSITORY_CACHE` shares verified archives across tests. Native runtime checks need driver-specific prerequisites. See [cache configuration](docs/api.md#caching-and-workers) for HTTP AC/CAS.

## Pull requests

Describe the problem, change, checks, and limits. Bug reports need a small reproducer, revision, command, SDK/Bazel versions, platform, and expected/actual results. Scrub logs before sharing; report vulnerabilities via [SECURITY.md](SECURITY.md). Keep SDKs, packages, build products, and raw reports out of Git. Contributions are [MIT licensed](LICENSE); preserve third-party notices.
