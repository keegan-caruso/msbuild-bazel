# Bazel-managed SDK toolchains

The migration removes host-path SDK acquisition in favor of verified downloads
and SDK artifacts produced by Bazel targets. Source-built runtime execution and
source-built SDK compilation are separate contracts.

## Step 1: remove empty runtime manifests

Removed the empty runtime-roots file from repository generation, toolchain
attributes, compilation requests and the runner. Sandbox roots still explicitly
include the SDK, runner and declared packages.

Validation on macOS ARM64: `bash scripts/check.sh`,
`bash scripts/check-dotnet.sh` and `bash scripts/check-analysis.sh` passed with
Bazel 9.2.0 and SDK 10.0.400. No GitHub CI was dispatched.
