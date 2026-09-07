# rules_msbuild naming

The project and Bazel module are named `rules_msbuild`, following the
[Bazel rules repository naming convention](https://bazel.build/rules/deploying).
The repository uses “adapter” for the implementation and “experiment” for bounded
validation work. The implementation plan is now `docs/implementation-plan.md`;
all repository links use that path.

## Current interfaces

- The versioned process driver is `python3 tools/adapter.py --request /absolute/request.json`. Its request and response schemas are unchanged.
- Repository environment variables and diagnostic markers use `RULES_MSBUILD_`.
  This includes `RULES_MSBUILD_DOTNET_ROOT`, `RULES_MSBUILD_BAZEL`,
  `RULES_MSBUILD_BAZEL_MODE` and the declared `RULES_MSBUILD_INPUT_` prefix.
- MSBuild fixture targets, properties and assembly namespaces use `RulesMsbuild`.
- Controlled fixture packages are `RulesMsbuild.BuildInputs`, `RulesMsbuild.Binary` and
  `RulesMsbuild.Leaf`. Build-package archives have new checksums because their names
  and payloads changed; archive verification remains enforced.

Shell wrappers, Nix environments, container definitions, workflows, action runners,
replay plugins, preparation tools, tests and documentation use these names together.
Update external scripts and environment overrides to the current names; no aliases
for previous names are provided. Regenerate prepared workspaces and fixture feeds
with this revision rather than mixing artifacts from before and after the rename.
Rebuild prebuilt toolchain images with `bash scripts/build-apple-container-image.sh`;
the current image tag is `rules_msbuild-toolchain:<architecture>`. Historical image
references and GitHub evidence links retain their original identifiers.

Historical findings use current interface names for readability. Retained raw logs
and reports from earlier revisions still contain the identifiers emitted by those
revisions. Their recorded outcomes are historical evidence, not reruns of the
renamed implementation. New validation results are recorded below.

## Validation

Validation used native macOS ARM64, .NET SDK 10.0.100 and Bazel 8.4.2.

- `bash scripts/check.sh`: passed, including pinned Starlark formatting/lint.
- `bash scripts/dotnet.sh run --project tests/ActionRunner.Tests -c Release`: passed.
- `python3 -m unittest discover -s tests/bootstrap -v`: 8 passed.
- `python3 -m unittest discover -s tests/starlark -v`: 13 passed.
- `python3 -m unittest discover -s tests/starlark_extensions -v`: 5 passed.
- `python3 -m unittest discover -s tests/graph_packages -v`: 16 passed and two
  source-dependent Serilog checks skipped in 220.794 seconds. With
  `RULES_MSBUILD_SERILOG_SOURCE` and `RULES_MSBUILD_SERILOG_PACKAGES` set to the
  acquired pinned inputs, `python3 -m unittest discover -s tests/graph_packages
  -k unchanged -v` passed both skipped checks in 8.399 seconds. All 18 distinct
  package checks therefore have passing evidence.
- `python3 -m unittest discover -s tests/e2e -v`: 14 passed, one opt-in native-runtime
  closure test skipped, in 271.449 seconds. This includes renamed build/binary
  packages, action identity, deterministic staging, relocation and public replay.

An independent Bazel consumer declared `bazel_dep(name = "rules_msbuild",
version = "0.0.0")` with a local path override and loaded
`@rules_msbuild//bazel:msbuild.bzl`. A query returned both the consumer target and
the external rule file. The first manual query used invalid multi-argument syntax;
the corrected single `set(...)` expression passed.

Current-source scans found no previous terminology in filenames or file contents.
Changed Python/JSON, workflow YAML, renamed documentation links, all three package
archive hashes and `git diff --check` passed. Existing external evidence identifiers
are intentionally retained.

Logs are under `/private/tmp/rules-msbuild-checks`; the complete e2e log is
`/private/tmp/rules-msbuild-e2e.log`. Linux, rebuilt container images and the
opt-in runtime closure are not newly qualified by this rename.
