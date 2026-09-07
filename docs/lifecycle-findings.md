# R06 lifecycle: initial command and output-ownership characterization

The initial slice distinguishes ordinary MSBuild lifecycle targets from Bazel
output cleanup and cache recovery. It does **not** add a Clean/Rebuild API to the
generated adapter or qualify the complete `lifecycle` roadmap node.

```sh
python3 -m unittest discover -s tests/lifecycle -v
python3 tools/probe_lifecycle.py --output artifacts/lifecycle-probe
```

The probe requires a new output path and native sandbox capability. It creates
separate ordinary and generated copies of the package-free Release/net10.0
diamond; checked-in fixtures are never built. It retains commands, raw logs,
execution records and every bundle file with content hashes and executable flags.

## Measured command contract

On 2026-09-06, native macOS ARM64 with pinned Nix SDK 10.0.100/MSBuild
18.0.2.52411 and Bazel 8.4.2 passed all seven characterization tests. Evidence:
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/msbuild-lifecycle-n25ou9ka/probe`.
The commands use the explicit installed tool paths through `RULES_MSBUILD_DOTNET_ROOT`
and `RULES_MSBUILD_BAZEL`; normal wrapper pinning remains unchanged.

| Operation | Observed behavior |
| --- | --- |
| MSBuild Release `Clean -graphBuild -isolateProjects` | Removes all four Release assemblies without compilation; preserves Debug output bytes, restore assets and an unrecorded file in App's Release bin directory. |
| Separate Release `Build -graphBuild -isolateProjects` after Clean | Compiles all four projects and reproduces the ordinary output. |
| Release `Rebuild -graphBuild -isolateProjects` | Fails `MSB4252` for missing dependency `GetTargetFrameworks` results. All four compile markers are attempted, App additionally reports `CS0103`, and App.dll is absent afterward. |
| Conventional recursive MSBuild Release `Rebuild`, without graph/isolation switches | Succeeds, compiles all four projects, preserves Debug bytes and the unrecorded Release-bin file. This is a separate oracle, not a change to adapter isolation. |
| Bazel `clean`, then `build //:all` | Deletes the active output trees; next build restores all four projects from disk cache with zero project executions. |
| Bazel `clean --expunge`, then `build //:all` | Removes the selected output base; next build again gets four disk hits and zero project executions. |
| Delete Shared's generated bundle, then build | Shared is recovered by one disk hit; no project executes. |
| Delete App's generated bundle, then build | App is recovered by one disk hit; no project executes. |
| Expunge, then build using a new empty disk-cache directory | All four projects execute under `darwin-sandbox`; no disk hits occur. |

Every successful build runs App and prints
`shared-v1:left|shared-v1:right`. All six recorded Bazel cases, including the
forced fresh execution, have the same complete bundle digest:
`5753961d5e63705e0116fbd951ce06c7f22ec3641e48875607a033017ce45fe2`.
The suite recomputes each retained hash and executable bit. Real action logs
contain exactly one project-relative compile marker and report local-only
execution/cache flags. Their actual MSBuild commands contain Build and replay
support targets, never Clean or Rebuild.

The first run stopped at the unexpected isolated-Rebuild failure. The final probe
retains it as a named negative control with the specific `MSB4252` diagnostic;
it does not silently remove isolation to turn the same command green. The
subsequent conventional Rebuild uses a distinct recorded command and result.

## Output ownership established by these controls

Ordinary SDK Clean follows its recorded output list for the selected
configuration. An unknown file inserted into the Release bin directory survives
Clean and conventional Rebuild. Restore metadata also survives. Debug preservation
is measured only in the ordinary SDK copy; generated graph execution currently
supports Release, so this does not establish generated configuration isolation.

Bazel owns the complete declared tree artifact: a test file inserted inside App's
bundle is removed by `bazel clean`. A user file outside those output trees,
the generated .NET source/restore/runner inputs and BUILD plan are preserved.
An independently materialized second output base keeps identical producer and
consumer bundle bytes after cleanup of the first base. This measures output-base
ownership, not support for a second .NET configuration.

The external disk cache survives both cleanup commands. Cleanup and cache purge
are separate operations: neither `clean` nor `clean --expunge` here means actual
recompilation. The forced-fresh control selects a new empty cache instead of
purging the earlier shared cache. Manual output deletion is an experiment on
throwaway Bazel outputs, not a newly supported selective-clean command.

The preparation checkout is deleted before generated execution, and both clean
recovery and manual producer/consumer deletion recovery operate without it.
Diagnostic logs remain outside consumer bundles. The fixture has no package
runtime assets or application-specific outputs beyond the existing adapter scope.

## Production requirements and milestone disposition

The current graph request/rule has no lifecycle target-selection API. A complete
R06 lifecycle implementation still needs:

- An explicit command contract separating source-workspace cleanup, generated
  output cleanup, cache purge, cache-permitting rebuild and forced compilation.
- An ownership policy for selected configured nodes and their artifacts,
  diagnostics and downstream invalidation. Destructive commands must run outside
  ordinary cacheable Build actions; a cache hit must never skip a requested deletion.
- A proven isolated target/result contract for Rebuild, including the missing
  `GetTargetFrameworks` handoff exposed here. Conventional recursive success is
  not evidence that graph Rebuild works.
- Validation for supported multiple configurations as R03 expands, interrupted
  cleanup/rebuild, stale custom output removal, concurrent readers and recovery
  after partial operations.
- Native Linux acceptance of this characterization before extending its platform
  claim; package/custom-target lifecycle behavior requires separate evidence.

Disposition: initial lifecycle characterization is implemented and measured on
macOS. The `lifecycle` node remains open for the production API and remaining
acceptance gates. No remote/cache-portability, full host-closure or performance
claim follows. Native runs overlapped other track work and establish correctness
only.
