# MSBuild graph-cache migration

## Direction

The intended primary build is one Bazel action per MSBuild traversal graph.
MSBuild keeps project evaluation, SDK targets, NuGet behavior, and graph
scheduling. A `ProjectCachePluginBase` implementation checks each configured
project before MSBuild builds it. Bazel still declares the graph action's
source, SDK, package, tool, and output inputs. Its ordinary action cache can
reuse an unchanged whole graph; the project cache handles edits within that
graph.

The current per-project Bazel rules remain the default during migration.
Their input and output contracts cover cases the graph plugin does not yet
cover. Replacing them before those contracts are transferred risks incorrect
cache hits.

## First cache handoff

The test-only graph probes can use `RULES_MSBUILD_PROJECT_CACHE_URL` to read
and publish project snapshots through the same HTTP cache service Bazel uses.
Each project fingerprint gets a domain-separated action-cache key. The
manifest and owned files are stored by digest in the CAS. The action-cache
entry is a valid `ActionResult` pointing to the manifest, so the pinned
`bazel-remote` server retains its normal validation. Every downloaded blob is
hashed again before replay. This is a separate client of the cache service;
Bazel itself still sees a whole-graph action.

The bounded Bazel qualification builds two independent three-project graph
actions with no fixed seed target. The Base action published three snapshots;
the body-edited action fetched two and rebuilt one. A no-cache action rebuilt
all three. The edited app ran with the new value, and each project's captured
outputs matched the no-cache control. A standalone qualification also
replayed the edited graph at a third workspace path with three hits and
compared its outputs with the edited build. Run with a pinned SDK and local
cache service:

```sh
RULES_MSBUILD_DOTNET_ROOT=/absolute/path/to/pinned/sdk \
  python3 tests/explicit_msbuild/cache_extension/qualify_remote.py \
  http://127.0.0.1:9090
RULES_MSBUILD_DOTNET_ROOT=/absolute/path/to/pinned/sdk \
  python3 tests/explicit_msbuild/cache_extension/qualify_bazel_remote.py \
  http://127.0.0.1:9090
```

On macOS ARM64 with SDK 10.0.400, Bazel 9.2.0, and pinned `bazel-remote`
2.6.2, one Bazel run reported 0/3 hits/misses for Base, 2/1 for the body
edit, and 0/3 for the no-cache control. The probe process took 1.13, 0.89,
and 1.05 seconds respectively. These are probe times inside actions, not
end-to-end Bazel build times or a performance comparison with the existing
rules. The Bazel qualification used a local execution strategy so the action
could reach the loopback cache service.

Repeated standalone runs exposed intermittent DLL/PDB hash differences
between the edited cache replay and a fresh no-cache build, including when
the control reused the same source path. The app result remained correct.
`qualify_remote.py` keeps the exact-output assertion so this remains visible;
its `crossPathOutputMismatches` field separately reports differences from a
fresh build at another path. The cause is not yet isolated. A passing single
run is evidence for the transport and selected behavior, not a general
output-equivalence guarantee. Rebuilding and republishing an identical
fingerprint detected one conflicting snapshot in a later check; 49 subsequent
controlled runs passed. The store now rejects a conflicting existing entry
instead of overwriting it. The unusual output difference still needs an
identified cause before default migration.

## Orchard check

The same transport was added to the test-only Orchard profile. A disposable
copy of Orchard Core at `04467a3438d4255627c1a478598a1585b3ff2947`
used the CMS entry point, SDK 10.0.400, Release `net10.0`, four MSBuild
nodes, and 403 graph nodes. The first remote seed took 97.45 seconds,
including publishing its snapshots. A clean remote replay hit all 202
configured projects; all 16,448 captured `bin/Release` and `obj/Release`
files matched the seed. The setup page and three embedded assets served from
the replayed output.

A later run against the populated cache measured 9.66 seconds for clean
replay, 11.28 seconds for the Abstractions body edit (201 configured hits and
one configured miss), 43.39 seconds for a deliberately forced no-cache
control, and 10.50 seconds for replay from the derived entries after deleting
the local seed. The edited project's DLL, PDB, and reference assembly matched
the control, and both edited builds served matching assets. As in the earlier
local-seed qualification, 752 of 12,800 wider semantic output files differed
from the independent control because Orchard's interceptor generator embeds
random GUIDs. These single runs do not establish a speedup over warm raw
MSBuild. Reproduce with:

```sh
RULES_MSBUILD_DOTNET_ROOT=/absolute/path/to/pinned/sdk \
NUGET_PACKAGES=/absolute/path/to/pinned/packages \
  python3 tests/explicit_msbuild/cache_extension/qualify_orchard.py \
  /path/to/disposable/orchard /path/to/results \
  --remote-url http://127.0.0.1:9090
```

## Requirements before changing the default

1. Move the probe out of `tests/` into a generic graph runner. Its current
   fingerprint discovers selected project files, evaluated items, shared
   directories, package archives, and reference outputs for the pinned
   Avalonia, Orchard, and runtime profiles. It must account for imports,
   generated inputs, task reads, SDK and package bytes, target properties, and
   native tools generically. Unknown inputs must cause a safe miss or a
   qualification error.
2. Capture the full output closure and target results for build, test,
   publish, and generated files. The small probe now stages apphosts and
   dependency PDBs as well as DLLs. Orchard still requires broad `obj/Release`
   snapshots; path-sensitive generated output needs a stable-path contract
   before it can be shared across workers.
3. Make the graph rule consume declared source, SDK, package, and tool inputs
   through the public facade. Configure cache credentials and endpoints
   without hard-coding a loopback URL in a BUILD file. Prove a fresh worker
   can retrieve a snapshot from the shared service, validate outputs, and
   serve the app. The tests here used one macOS host and local execution.
4. Compare body, API, resource, test, and publish edits on larger graphs
   against warm raw graph-mode MSBuild and the current per-project rules.
   Earlier Avalonia and runtime probes did not beat raw graph-mode edits;
   preserving correctness alone is insufficient to justify switching the
   default. After the graph route passes, update generator and macro defaults,
   then remove the per-project compile path separately.

The remote project store currently uses no authentication, retries, batching,
or cross-process locking. A missing entry falls back to MSBuild compilation;
a malformed, corrupt, or conflicting entry fails the build. The small test is
package-free, and Orchard's input discovery remains profile-specific. Neither
run proves general remote-cache correctness or remote execution.
