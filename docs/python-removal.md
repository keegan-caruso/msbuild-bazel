# Production Python removal

The migration retains Python for repository tests, acceptance probes and benchmarks.
Production preparation, Build/Test orchestration, reuse, transport and bootstrap
move to .NET with a minimal shell SDK bootstrap. The existing MSBuild/Bazel
contracts and project-owned target frameworks remain authoritative.

## Sequence

1. Separate production helpers from experimental harness imports.
2. Port fresh graph preparation and compare outputs/rejections with Python controls.
3. Port Build/Test orchestration, local preparation reuse and remote snapshots.
4. Remove Python from setup and normal tooling; qualify a Python-free environment.

Each step is committed separately after its relevant checks. Until the final gate,
Python remains required by production paths that have not yet migrated.

## Step 1: production dependency boundary

Moved Bazel execution-record parsing and native fixture eligibility into production
modules. Existing probes import those helpers. The native workflow no longer imports
probe modules or their test fixtures.

Validation: `python3 -m unittest discover -s tests/production_boundary -v` and
`TMPDIR=/private/tmp python3 -m unittest discover -s tests/native_cache -v`: all 24 tests passed on native macOS ARM64. The HTTP tests required local socket access outside the execution sandbox; the canonical temporary path avoids the existing `/var` versus `/private/var` fixture mismatch.
This is dependency cleanup, not yet removal of the Python runtime.
