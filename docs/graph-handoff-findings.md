# Generated graph discovery and handoff controls

This R01 track hardens the existing package-free Release/net10.0 graph boundary.
The entry point remains MSBuild; Bazel schedules configured project actions.

## Contract changes

Graph manifest schema 1 gains additive `entryRequests`: the original logical entry
project paths and global properties. Preparation requires this field; regenerate
older manifests. After validating each recorded input digest, preparation runs
GraphExport again with those entries and compares the complete fresh manifest.
New globbed sources, newly present optional imports and changed conditional edges
therefore reject an old saved manifest with `stale graph discovery` even when all
previously recorded file digests still match. This is evaluation, not compilation.
Existing missing/stale-input diagnostics remain separate from discovery rejection.

Preparation builds in a private sibling directory and renames the completed plan
into its final output. Interrupted preparation cannot expose a partial final plan;
retry uses the original final path. An advisory checkout-local lock serializes the
shared adapter builds and publication. Separate successful preparations retain
separate output paths; an existing output is rejected. A hard kill may leave an
unpublished `.graph-prepare-*` directory for manual cleanup.

`BazelExtraInput` evaluation inputs now accompany dependency projects and imports
through the transitive evaluation closure. The conditional-edge fixture explicitly
declares its `Exists` selector this way. Dependency source files remain excluded.
Arbitrary undeclared filesystem probes are not automatically traced or supported.
Preparation assumes an otherwise stable source tree during validation and copying;
this lock does not prevent an editor or another checkout from changing inputs.

Generated graph bundles gain `bundle.json`, schema 1, containing `resultsSha256`
and `artifactsSha256`. The runner validates this seal before parsing replay results
or staging artifacts, then validates each artifact's existing digest. The seal is
written only after the payload is complete, normalized, and ready to consume.
Its own mode/timestamp are normalized before final publication. A missing seal
means `dependency bundle incomplete`; altered result/manifest bytes mean
`dependency bundle metadata corrupt`. Old unsealed graph bundles must rebuild.
The explicit two-project bundle format is unchanged. A graph runner attempt also
rejects a nonempty existing output, preventing a failed retry from retaining a
previous success marker. Bazel remains responsible for cache publication only on
successful action completion.

## Executable controls

Run under the pinned toolchain (native sandbox access is required):

```sh
python3 -m unittest discover -s tests/graph_execution -p test_prepare_graph.py -v
python3 -m unittest discover -s tests/graph_handoff -v
```

The discovery tests retain old/new manifests, generated plans, execution logs and
reports under `graph-discovery-*` temporary directories. Independently adding an
App source or optional App import must execute App only; adding the declared Left
selector must introduce Left -> Shared and execute Left plus App. Each starts with
a cold native build and retains a disk cache across regenerated workspace paths.
Concurrent preparations must produce identical plans and adapter payloads. A
controlled `KeyboardInterrupt` during payload copying must leave no final plan,
then an explicit retry must succeed.

The handoff tests first build the ordinary diamond and native Bazel baseline,
then copy legitimate bundles to a controlled **direct ActionRunner harness**.
Each consumer uses a fresh request/output, with no action cache enabled. Artifact
removal/corruption, an absent completion seal and stale result bytes must reject
before replay and compilation. Missing targets, incompatible globals and an
invalid root token in returned metadata deliberately update the transport seal;
they must reach `SPIKE_REPLAY_REQUEST`, reject semantically, and never compile a
dependency or consumer. Two simultaneous valid App consumers must use distinct
scratch paths, compile only App, replay Left/Right/Shared and match ordinary output.
A repeated attempt cannot overwrite a completed output. Evidence is retained under
`graph-handoff-*`, including logs and per-case request/result digests.

These forced-consumption cases establish the actual adapter/replay boundaries;
they do not claim that modified bundles were transported through Bazel's cache.
The complementary cache track owns generated-output recovery and legitimate
producer-artifact changes versus an updated ordinary MSBuild baseline.

## Measured scope

Local validation uses macOS ARM64, SDK 10.0.100, MSBuild 18.0.2.52411 and Bazel
8.4.2 from the pinned Nix toolchain. All ten handoff/discovery tests passed in 110.7 seconds at revision
`f5cdae9`, including the warm-cache input controls and normalized generated
restore state. All 14 preparation rejection tests passed. The original two native
graph execution tests also passed before the final bundle-seal addition; the new
suite repeats the native diamond baseline with the final sealed bundles. Forced
consumer evidence is retained at `graph-handoff-rk4ad98s` under the native
temporary directory. Linux qualification belongs to the integrated native CI run. The tests
are correctness evidence, not contention-free performance measurements. No remote
cache, cross-platform reuse, multiple configurations, general NuGet, crash-durable
filesystem transaction, or arbitrary MSBuild filesystem discovery is established.

Generated restore state also replaces NuGet `project.nuget.cache`
`dgSpecHash` with `$NORMALIZED`. This is a path-derived restore diagnostic hash,
not an independently consumed package digest. Keeping its original value changed
Bazel restore inputs solely after workspace relocation; the cache track verifies
the resulting relocated action reuse.

Keep the Git revision stable for an entire cache experiment: a commit made during
an earlier run changed the SDK-generated adapter assembly revision metadata.
Execution-log comparison isolated the resulting misses to `ReplayPlugin.dll` and
`ActionRunner.dll`; the unchanged-revision rerun above passed every action-set
assertion. This is an input-identity change, not a relocation failure.

An integrated run exposed a separate test-environment drift: Shared's only changed
input was its generated restore JSON. The assets and dgspec `configFilePaths`
switched between the wrapper's `.cache/dotnet-home` NuGet configuration and the
user-home NuGet configuration. The resulting conservative rebuild was correct;
the test's supposedly unchanged restore environment was not. Discovery tests now
set one fixture-local `DOTNET_CLI_HOME` for restore, export, preparation children
and Bazel, and disable reusable MSBuild workers (`MSBUILDDISABLENODEREUSE=1` plus
`-nodeReuse:false` on restore). This keeps earlier wrapper-based tests from
contributing a different worker environment to an action-set comparison.

Validation of that environment fix ran `bash scripts/dotnet.sh run --project
 tests/ActionRunner.Tests -c Release` immediately before `python3 -m unittest
 discover -s tests/graph_handoff -p test_graph_discovery.py -v`, with the pinned
Nix tool overrides. Runner contract/process tests and all six discovery tests
passed (93.9 seconds for discovery). In retained `graph-discovery-vr00vjeh`, both
Shared restore snapshots list the same normalized fixture-local NuGet
configuration path and the conditional change executes exactly Left plus App.
