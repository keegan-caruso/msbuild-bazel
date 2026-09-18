# .NET remote-cache measurement protocol

Declared before collecting timings. Related to #41/#42; measurements and
same-host rehearsals do not establish acceptance on a second physical host.

- Candidate: new .NET worker-identity implementation, exact commit recorded in report.
- Workloads: four-project package-free diamond first; pinned Serilog approval graph
  at `49b5339ce85385dc52d4d8e8f2b8308becf23506` second.
- Three repetitions, alternating raw/adapter execution order by repetition.
- Cases: fresh unchanged remote recovery, implementation edit, public API edit,
  and empty remote cache. Each adapter consumer starts with fresh source, state,
  preparation and Bazel directories. Producer source/state is removed first.
- Raw comparator: ordinary MSBuild Build then application/VSTest execution with
  matching configuration, target framework, path mapping and package inputs.
  Unchanged/edit comparisons use raw retained incremental state; empty-cache
  comparisons use raw fresh state. This gives raw MSBuild its normal local advantage.
- Body edits preserve public API. API edits on Serilog update the expected approval
  file for performance samples; a separate negative control must still reject
  mismatched approval data. Expected compile counts are asserted per workload/case.
- Include .NET process startup, identity verification, staging/preparation, all HTTP
  cache transfer, Bazel startup/build/test, final validation and publication.
- Exclude tool/package acquisition and Restore for both paths. State these costs
  separately; a build is never secretly restored by the action.
- Record individual samples and medians, adapter/raw ratio, phase times, compiler
  invocations, request counts and CAS payload bytes. Retain actual outputs and test
  counts/hashes. Do not infer useful scale performance from a four-project graph.
- Use pinned bazel-remote 2.6.2 with real disk storage. The local baseline is loopback,
  unshaped transport. Separate-worker/LAN timing is labeled separately if available.
- The previous 1.25x + 0.250 s warm/edit target is retained as a diagnostic comparison,
  not relaxed after results. Cold overhead is descriptive under the agreed scope.


Expected adapter work sets: unchanged 0, body 1, API/empty 4 for the diamond;
unchanged 0, body 1, API/empty 2 for Serilog. The diamond API count was corrected
in preflight from 3 to 4 after inspecting `DependencyIdentity`: the existing
policy includes the recursive dependency API closure, so the entry also misses.
DLL/PDB parity with raw MSBuild passed for that control. No performance threshold
was changed. Preflight results are excluded from the final three repetitions.


The initial Serilog pair revealed an external-source PathMap mismatch: the raw
compiler includes `Microsoft.NET.Test.Sdk.Program.cs` from the global cache while
the adapter stages it under `workspace/.nuget/packages`. The raw Serilog command
therefore maps the global package root to `/_/workspace/.nuget/packages` as well
as mapping source to `/_/workspace`. This matches the adapter's logical locations;
DLL/PDB equality remains mandatory. The failing Serilog sample is excluded. The
12 completed diamond samples remain valid: its command and source roles did not
change. Serilog is measured separately for all three repetitions after this fix.
