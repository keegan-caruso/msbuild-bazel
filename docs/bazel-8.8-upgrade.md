# Bazel 8.x baseline: 8.8.0

The supported 8.x baseline moves from 8.4.2 to exact release **8.8.0**.
Bazel 9.2.0 remains the default in `.bazelversion`, Linux bootstrap and Nix.
No SDK, rule implementation or default module lockfile changes are needed.

## Pins and selection

- `nix/bazel-versions.json`: retain the existing verified macOS ARM64 8.8.0
  download and remove 8.4.2 from the selectable matrix.
- `nix/bazel-linux-versions.json`: replace Linux x86-64 8.4.2 with 8.8.0.
- Select `nix develop .#bazel-8_8_0`, or set both `RULES_MSBUILD_BAZEL` and
  `RULES_MSBUILD_BAZEL_VERSION=8.8.0` for an existing installation.
- The old `.#bazel-8_4_2` shell is retired. Historical experiments require their
  original revision; their measured results have not been relabeled.

The hashes were checked against the official release checksum files at
`https://releases.bazel.build/8.8.0/release/`:

| Platform | SHA-256 |
| --- | --- |
| macOS ARM64 | `f0ac192aba2ccaa373cdfd527d4c407cc492c1296a2f11a4b67563e4d5aa9acb` |
| Linux x86-64 | `ca189f994f632c91c275443b8571652e3ea190fc2437a5798121ba7e5a9a2f29` |
| Linux ARM64 qualification binary | `861bc2fb6adb9db2e1daa409d4503605475d374ff63c25fe96b3330063151fd5` |

## Validation

- Native macOS ARM64 Nix shell: actual 8.8.0 binary, toolchain and Starlark
  checks passed. Six tooling tests passed. SDK repository tests: two passed,
  one skipped because the pinned extra Nix import was unavailable.
- Linux x86-64 Nix shell evaluation resolves 8.8.0. No x86-64 build was run.
- Ubuntu 22.04 Linux ARM64, SDK 10.0.400: checksum-verified 8.8.0 passed
  toolchain checks and explicit persistent-worker acceptance twice, with ordinary
  restore and `RULES_MSBUILD_SHARED_RESTORE=1`. Both runs passed isolation,
  dependency validation, compilation failure/recovery, source-edit invalidation
  and producer-deleted relocated disk-cache recovery. Shared restore also passed
  actual recompilation using recovered metadata at the relocated workspace.
  Commands: `python3 tests/explicit_msbuild/acceptance.py /tmp/bazel88-acceptance`
  and the same harness with shared restore and a fresh output directory.
- Reports are retained locally under ignored `artifacts/bazel-8.8/`; the disposable
  container was removed after validation.

The full Orchard benchmark and independent HTTP-cache recovery were not rerun.
Existing full-graph timing comparisons cover 8.4.2 and 9.2.0, not 8.8.0.
No GitHub workflow was triggered.
