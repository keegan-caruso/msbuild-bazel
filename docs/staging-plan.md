# Deterministic staging experiment

This is the first slice of the native-runtime/staging milestone. Native runtime
closure remains separate; remote execution and remote caching stay disabled.

## Acceptance contract

Run `python3 tools/probe_bazel.py --staging-probe --output ABSENT_DIRECTORY`
inside the pinned development environment. Copy and restore the fixture as in
the existing Bazel probe, then compare a cold build against a second build using
a fresh output base and a separate empty disk cache, with identical source inputs.
Both Shared and App must actually execute inside the native sandbox on both runs.
Their scratch workspace paths must differ. Compare the complete consumer bundle
file sets, SHA-256 digests and executable bits, including result metadata and
artifact manifests, not just DLLs or application output.

Keep diagnostic logs and action reports in separate declared outputs. They retain
real paths and timings for diagnosis but must not enter the downstream bundle.
Preserve executable app hosts. Map compiler source paths to a stable logical
workspace; do not rewrite compiled binary bytes. Stage only the explicit fixture
handoff artifacts, rather than incidental SDK bookkeeping files. Any exclusions
must be documented and dependency replay must still succeed without recompilation.

The existing source-edit, disk-cache recovery, undeclared-input, identity and
package tests must continue to pass. This demonstrates repeatability on one host
and SDK for the narrow fixture; it does not prove a complete native runtime
closure, arbitrary project output discovery, or cross-platform reproducibility.
