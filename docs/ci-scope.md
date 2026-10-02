# CI scope

GitHub CI runs only by explicit `workflow_dispatch`; no push/PR trigger. Do not
start it without a maintainer request. The workflow provides quick/full Linux
checks; full adds graph acceptance. Download/bootstrap caches are distinct from
action-cache correctness and are not evidence of network-fresh acquisition.

Local validation uses `scripts/validation.sh` phases: `common`, `version`, and
`acceptance` with a fresh report directory. `scripts/test-bazel-matrix.py` covers
Bazel 8.8 and 9.2. Linux persistent workers additionally need nested namespaces
and the [qualified ARM64 container](apple-container-runbook.md).

A successful test qualifies its recorded SDK, version, architecture and slice.
Linux x86-64/RBE/macOS-worker support does not follow from ARM64 evidence.
