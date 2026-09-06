# MSBuild result-cache path experiment

## Question and method

Before adding Bazel actions, distinguish movement of the exported output bundle
from movement of the absolute project paths recorded by MSBuild.
`tools/probe_paths.py` runs three cases on copied fixtures with Release/net10.0:

1. Restore and build Shared, move its whole bundle to a different output
   directory, delete both projects' bin/obj, and restore only App's saved restore
   metadata. Build App through the unchanged v1 driver using the moved bundle.
2. Delete the producer workspace entirely, create a fresh consumer workspace at
   another absolute path, and restore there with a fresh workspace-local NuGet
   directory. Copy the original Shared bundle's artifacts into the new paths.
   Invoke MSBuild directly with the original opaque results cache and
   `-isolateProjects`. This intentionally bypasses only the driver's workspace
   check; the cache bytes and manifest are not edited.
3. Delete bin/obj again, restore, and build a fresh Shared cache at the consumer
   path. Delete Shared's local bin/obj and build App through the driver using
   this fresh bundle. This checks that the consumer path/toolchain can build and
   still requires dependency artifact handoff.

The probe preserves logs, requests, `raw-relocation/command.json`, bundles, and
`report.json`. The report records process exit codes, compilation markers from
MSBuild logs, and independently executed application output. The script exits
nonzero for failed preparation or control builds, but records the raw relocation
status without prescribing an outcome. The e2e test asserts the observations
below, so a changed cache behavior will require investigation.

## Measured result

On 2026-09-05, macOS ARM64 with the flake's .NET SDK 10.0.100:

```sh
nix --extra-experimental-features 'nix-command flakes' develop path:. --no-update-lock-file -c python3 tools/probe_paths.py --output artifacts/path-probe
```

| Case | MSBuild exit | Compilation markers | Application output |
| --- | --- | --- | --- |
| Moved bundle, same workspace | 0 | App only | `shared-v1/app-v1` |
| Original cache, new workspace | 1 | Neither | Build failed; not run |
| Fresh cache, new workspace | 0 | App only | `shared-v1/app-v1` |

The relocated build fails with `MSB4252`: the consumer requests
`Shared/Shared.csproj` at the new absolute path, with `Configuration=Release`,
for `GetTargetFrameworks`, but the engine has no cached build result for it.
Both Shared producer logs contain `SPIKE_COMPILE:Shared`. The original producer
workspace and original bundle directory are absent when the experiment ends.

The failure is produced by MSBuild itself, not by the v1 manifest validation.
Fresh App restore metadata at the consumer path and the successful fresh-cache
control narrow the immediate failure to lookup of the relocated dependency.

Validation in the same Nix environment: `bash scripts/check.sh` passed and
`python3 -m unittest discover -s tests/e2e -v` passed all seven tests in 27.599
seconds. `git diff --check` passed. These are native macOS results; Linux CI has
not been run locally.

## Implications and remaining limits

The bundle's container path can change in this experiment; the absolute project
identity cannot simply change alongside it. Copying the artifact tree is
insufficient to make the original results cache usable at another project path.
This result supports retaining the driver's same-workspace guard.

This does not prove that absolute paths are the only obstacle. Because the
relocated build stops at `GetTargetFrameworks`, it does not test downstream
artifact paths, generated files, debug paths, or package targets after a cache
lookup succeeds. The exported Shared obj files also contain producer restore
state. No cache serialization was decoded or rewritten.

No Bazel action, sandbox, disk-cache hit, Linux execution, or remote execution
was measured in this local run. Nix supplies an ambient SDK from its store; it
is not a declared Bazel toolchain. The existing Linux CI commands discover the
new test, but their results are pending.

Before writing the two-target rule, define its execution-log assertions and
prove how separate actions see the same absolute project paths without relying
on writable producer state. A fixed shared scratch directory with serialized
local actions could explore scheduling, but would not establish sandboxed
parallelism or portable caching. A sandbox strategy providing identical internal
paths needs its own measurement. Neither strategy is implemented by this probe.
