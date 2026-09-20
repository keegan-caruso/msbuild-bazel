# Orchard explicit-rule extensions

Correctness controls on Linux ARM64, SDK 10.0.400, Bazel 8.4.2, persistent workers.
Orchard source pin: `04467a3438d4255627c1a478598a1585b3ff2947`.

- Package tests: commit `a472d2c`.
- Project analyzer tests: commit `347d610`.
- Target items and module assets: implementation accompanying this evidence.

Nonzero exit codes in reports are expected rejection controls, not passing builds.
The cache excerpts demonstrate producer disk-cache hits with consumer worker
execution. These logs are correctness evidence; elapsed times are not benchmark
results. No full Orchard CMS performance comparison is claimed.

Each implementation step passed `scripts/check.sh`, `scripts/check-dotnet.sh`
(112 tests, with one Linux-only discovery control skipped on the macOS host), and
relevant Linux explicit-rule acceptance. Linux worker tests independently include
undeclared read/source-write controls and cache relocation.

See ../../orchard-package-semantics.md, ../../project-built-analyzers.md and
../../msbuild-target-items.md for scope, reproduction and remaining limitations.
