# Manual CI scope

GitHub CI runs only when requested. The
[Linux workflow](../.github/workflows/linux.yml) uses `workflow_dispatch`;
pushes and pull requests do not start it.
There is no macOS workflow; macOS qualification is local.

## Linux phases

After `bash scripts/setup.sh`, use [ci-linux.sh](../scripts/ci-linux.sh):

| Command | Checks |
| --- | --- |
| `bash scripts/ci-linux.sh quick` | Shared common and version phases: whitespace, unit/style checks, rule analysis and SDK repositories |
| `bash scripts/ci-linux.sh acceptance` | Explicit-rule acceptance in a fresh temporary directory; requires bootstrap tools; Bazel builds its runner |
| `bash scripts/ci-linux.sh full` | Quick, then acceptance |

`scripts/validation.sh` owns the `common`, `version`, and `acceptance` phases.
`ci-linux.sh quick` runs common plus version; the version matrix runs common once
and version/acceptance for each selected Bazel baseline. Local contributors can
invoke the same phases directly after setup.

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
