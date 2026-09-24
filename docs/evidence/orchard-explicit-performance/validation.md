# Validation

- Host `bash scripts/check.sh`: passed (toolchain, Starlark, scaffold).
- Host `bash scripts/check-dotnet.sh`: passed with retained code and 4 GiB budget;
  5 style, 33 preparation, 70 workflow (one environment skip), 9 explicit tests.
  Total: 116 passed, one skipped. Archive and runtime-collision controls included.
- Final Linux ARM64 worker acceptance: passed, including executable tests,
  implementation edit/reference stability, active/absent global property removal,
  declaration failures, read/write isolation, and relocated disk-cache recovery.
- Final Linux worker protocol: passed forged digest, undeclared request, similarly
  prefixed input, arbitrary tool-root and forged SDK-alias controls.
- Final Linux package-lock analysis: selected consumer version accepted;
  unresolved inherited conflict and direct-lock mismatch rejected.
- Full 202-project CMS build and body-edit reference stability: passed.
- Full relocated HTTP-cache recovery: 489 hits, zero compiler actions, passed.
- Recovered setup Razor page and three static assets: HTTP 200; static asset hashes
  match raw MSBuild. No tenant created.
- Python harness syntax and `git diff --check`: passed.

Earlier generator acceptance also passed helper implementation-edit, visibility,
role-mismatch and cache controls; the final full CMS build exercises the unchanged
Orchard generator with the retained runner. No GitHub CI was invoked.

Commands for final Linux controls (from `/workspace`, pinned tool environment):

```sh
RULES_MSBUILD_REPOSITORY_CACHE=/tmp/repository-cache \
RULES_MSBUILD_EXPLICIT_WORKER=1 \
python3 tests/explicit_msbuild/acceptance.py /tmp/retained-checks
python3 tests/explicit_msbuild/worker_protocol.py
RULES_MSBUILD_REPOSITORY_CACHE=/tmp/repository-cache \
python3 tests/explicit_msbuild/package_locks.py /tmp/retained-checks
```
