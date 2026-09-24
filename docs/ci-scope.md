# Manual CI scope

GitHub CI runs only on explicit request. The two workflows are
[Linux](../.github/workflows/linux.yml) and [Nix](../.github/workflows/nix.yml);
both use `workflow_dispatch` only. Pushes and pull requests do not start CI.
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
Verified tool downloads and repository-tool NuGet packages have separate caches.
Fixture package roots, bin/obj directories and Bazel action caches are excluded.
Acceptance evidence under `/tmp/msbuild-explicit-ci.*` is uploaded for seven days.
A restored download cache is not evidence of a network-fresh bootstrap.

## Nix

The separate Ubuntu 22.04 workflow enters the pinned Nix shell, acquires Starlark
validation tooling, checks tool pins, then runs `ci-linux.sh full`. Its timeout is
30 minutes. A workflow definition describes checks to run, not a passing result.

For local setup, see [development](development.md). For native Linux ARM64 checks
on an Apple silicon Mac, see [Apple containers](apple-container-runbook.md).
