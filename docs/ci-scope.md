# Manual CI scope

GitHub CI runs only on explicit request. The
[Linux workflow](../.github/workflows/linux.yml) uses `workflow_dispatch` only. Pushes and pull requests do not start CI.
There is no macOS workflow; macOS qualification is local.

## Linux phases

After `bash scripts/setup.sh`, use [ci-linux.sh](../scripts/ci-linux.sh):

| Command | Checks |
| --- | --- |
| `bash scripts/ci-linux.sh quick` | Diff whitespace, CI/bootstrap unit tests, scaffold Bazel query, owned .NET style/build checks and SDK repository tests |
| `bash scripts/ci-linux.sh acceptance` | Explicit-rule acceptance in a fresh temporary directory; requires the tools and runner already built |
| `bash scripts/ci-linux.sh full` | Quick, then acceptance |

Quick restores/builds repository tooling. Full adds the explicit acceptance
fixture; it does not run every upstream benchmark, worker probe or runtime suite.
Those qualification commands live in their individual reports.

The Linux workflow uses one Ubuntu 22.04 job with a 90-minute timeout. It runs
setup twice, then quick, and optionally acceptance when `full` is selected.
Bootstrap downloads and the Bazelisk cache are cached separately from repository-tool NuGet packages.
Fixture package roots, bin/obj directories and Bazel action caches are excluded.
Acceptance evidence under `/tmp/msbuild-explicit-ci.*` is uploaded for seven days.
A restored download cache is not evidence of a network-fresh bootstrap.

For local setup, see [development](development.md). For native Linux ARM64 checks
on an Apple silicon Mac, see [Apple containers](apple-container-runbook.md).
