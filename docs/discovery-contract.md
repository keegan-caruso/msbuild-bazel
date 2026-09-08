# RUL-5: discovery identity and eligibility

Status: qualified on 2026-09-08. The final matrices pass 27 small-graph/boundary
cases and 15 pinned Serilog cases; 31 identity/contract unit tests also pass.

The first complete identity contract covers `GraphExport`, including its SDK
discovery targets, for Release/net10.0 on the pinned Nix SDK 10.0.400, native macOS
ARM64. It includes the selected upstream Serilog library and small project graphs.
It does not enable production preparation reuse. RUL-6 owns prepared-artifact
integrity, publication, recovery and keeping the input lease through consumption.

## Why the fallback is necessary

The [observation experiment](evaluation-observation-findings.md) shows that XML
loading, property-function reads and item timestamps can bypass the public
filesystem hooks. Warm evaluation contexts also suppress observations. The
recorder therefore remains useful for imports and negative probes, but its trace
alone cannot authorize reuse. This implementation hashes the entire supplied
workspace and runtime/tool trees as the conservative fallback permitted by the
[design](preparation-observation-design.md).

No directories are implicitly excluded: source, new or removed names, empty
directories, nested imports, generated NuGet wrappers, restore state, package
payloads and consumer extra files participate. File modes and content participate;
timestamps do not enter the content key. Request properties, controlled effective
environment, policy/schema, controller source, compiled tool payloads, SDK/runtime
closure, OS build and boot session also participate. Changing a consumer-supplied
version/date/random value in an existing input invalidates the candidate; no new
MSBuild property is introduced.

## Supplied input semantics

`tools/discovery_contract.py` creates an owned, separately locked state directory.
It copies the input workspace and prebuilt exporter/recorder tools into a private
view. Workspace symlinks and special files are rejected. Source mutations detected
during copying reject capture. Restore metadata's embedded source-root paths are
relocated to the supplied workspace; authored project/source bytes are preserved.
Workspace file/directory modification and access times are normalized to
2000-01-01 UTC. Nix supplies the immutable runtime closure at its pinned paths.

Identity describes those exact supplied bytes and paths. It does not assert that
the mutable source checkout was atomically snapshotted, or that ordinary MSBuild
at another absolute path has identical semantics. Ordinary parity is tested using
the same supplied view and effective environment. Each capture uses fresh .NET
processes, with workload resolution disabled and an explicitly constructed
environment; it does not inherit ambient user environment variables.

Both graph evaluation and full export run under a deny-by-default native sandbox.
The workspace, copied tools and Nix closure are readable; only dedicated scratch
and output paths are writable. Network access is denied. SDK runtime support has
explicit access to OS libraries, dyld caches, ICU data, required ancestor metadata,
root-directory opening and runtime services. These are same-host/same-boot
assumptions, not a general remote-execution or full host-closure claim. Successful
external observations, scratch-dependent evaluation, and existing external inputs
hidden by sandbox denial reject eligibility. Recorded external absences are
rechecked before accepting a candidate, including when all declared tree hashes
still match.

## Qualified behavior

Eligibility uses an allowlist, not a clean diagnostic scan:

- Authored project/import XML accepts the property/item forms implemented in
  `check_xml`. MSBuild resolves all nested, conditional, property-selected and
  wildcard imports. Every actual imported workspace file is checked, regardless
  of its extension. An unimported file becoming selected changes the tree key and
  must pass a fresh capture before eligibility can be established.
- Custom targets, task registrations, initial targets, custom SDK resolvers,
  arbitrary property functions and item timestamp expressions reject eligibility.
  The three exact pure expressions used by the selected Serilog source are
  qualified explicitly. Application source clock calls are unaffected.
- `tools/discovery-sdk-imports.json` records the 94 pinned SDK import payloads
  observed in these slices. A different SDK/host import rejects eligibility; simply
  being located in the SDK read domain is insufficient.
- PolySharp 1.15.0 and Microsoft.NET.ILLink.Tasks 10.0.11 are the qualified package
  behaviors. Existing archive pins and archive-derived payload verification run
  before discovery targets execute. Only their selected build imports are trusted;
  extra or modified package payloads reject capture. Their compile/publish targets
  are not permission to run arbitrary discovery hooks.
- The exporter still runs `BazelGraphExportContract`, including
  `ProcessFrameworkReferences`, `ResolvePackageAssets`, `ResolveLockFileAnalyzers`
  and `ResolveTargetingPackAssets`. This is not an evaluation-only certificate.
  Compilation, generators, tests and publish targets do not run in capture.

The support boundary is intentionally narrower than all existing build-action
acceptance. Unsupported requests receive no eligible certificate and must use
fresh preparation. In particular, this does not qualify arbitrary R05 generator
targets, Git/version tasks, other SDKs, frameworks, configurations or packages.

## Capture and revalidation API

Build `tools/GraphExport` and `tools/EvaluationProbe` with the repository wrapper.
Provide an entries JSON array, for example:

```json
[{"project":"src/Serilog/Serilog.csproj","globalProperties":{"Configuration":"Release","TargetFramework":"net10.0"}}]
```

```sh
python3 tools/discovery_contract.py --workspace /path/to/restored-source \
  --state /path/to/new-owned-state --entries /path/to/entries.json
```

Successful capture writes the graph, complete evaluated import/observation
evidence and `output/certificate.json`. The certificate binds content identity,
policy, operation, graph digest and negative observations. Copy it outside the
owned state before subsequent calls: that state's workspace/tools/output are
disposable and replaced under its lease.

```sh
python3 tools/discovery_contract.py --workspace /path/to/restored-source \
  --state /path/to/owned-state --entries /path/to/entries.json \
  --candidate /path/to/saved-certificate.json
```

Candidate validation rebuilds and hashes the supplied view, checks certificate
integrity and external absences, and reports whether it is unchanged **without
executing MSBuild discovery**. A changed candidate is ineligible; request a fresh
capture to learn its new graph. Both paths report `reuseEnabled=false` because
neither returns a cached prepared artifact. A JSON result is evidence from that
call, not a durable lock. RUL-6 must retain a lease through artifact verification
and consumption and bind the complete materialization/test/tool request; it must
not use this GraphExport certificate to skip arbitrary preparation operations.

## Acceptance

Run the native probes with pinned tools installed and prebuilt:

```sh
python3 -m unittest discover -s tests/preparation_reuse -v
python3 tools/probe_discovery_contract.py --output /tmp/discovery-contract
python3 tools/probe_serilog_discovery.py --source /path/to/serilog-git-acquisition \
  --packages /path/to/package-cache --output /tmp/serilog-discovery-contract
```

The Serilog probe archives the unchanged upstream revision
`49b5339ce85385dc52d4d8e8f2b8308becf23506` into a disposable workspace and restores
the selected library using the two supplied pinned packages. It never builds the
acquired source checkout directly. Reports preserve ordinary export parity,
repeated fresh capture, candidate validation, timestamp-only controls, source,
version/import, signing/resource, restore and package mutations, and corrupt
package rejection. The small matrix additionally checks actual external-read,
sealed-input-write and loopback-network denial, optional/wildcard/reference
changes, masked external inputs, custom executable XML, symlinks and corrupt
certificates. See the final validation record in the implementation plan.

This establishes correctness for the selected discovery boundary, not reduced
latency. Full-tree copying/hashing is deliberately conservative. RUL-7 measures
its cost; narrowing a domain requires independent coverage evidence.
