# R04 library integration and correctness review

The selected pinned Serilog library now builds unchanged in a native macOS ARM64
Bazel action, retaining SDK/MSBuild compilation. It preserves signing, the embedded
ILLink resource, XML documentation, logging behavior and PolySharp-generated
internal types. All five independent mutations (source, resource, key, version
import and generator option) rebuild one action and match ordinary MSBuild.
Producer-free relocated disk-cache recovery executes zero actions and preserves
all bundle bytes and executable modes; the recovered DLL runs in a real consumer.
See [Serilog adapter findings](serilog-adapter-findings.md) for the pinned source,
commands and complete retained report. The standalone
[API oracle](serilog-api-oracle-findings.md) uses upstream options and approved text;
both final cold and relocated DLLs match the upstream approved API text byte for
byte. It does not execute the upstream xunit test project.

## Correctness corrections established by this slice

| Issue | Resulting contract and control |
| --- | --- |
| Evaluation misses implicit references and resolved generators | Selected SDK resolution targets discover the actual analyzer set without CoreCompile. |
| MSBuildAllProjects omits nested imports | ProjectInstance.ImportPaths supplies the evaluated import closure; nested-file edits change the manifest. |
| Nix SDK imports files outside its root | Two measured external imports are explicit hashed SDK inputs; other host imports remain rejected. |
| Python normalizes CRLF while .NET preserves it | BOM-aware byte decoding preserves line endings during normalized hash verification. |
| Missing key changes conditional signing | Key bytes and signing state are declared, and dependency evaluation stages the key. |
| Signed NuGet restore hash differs from archive hash | Two qualified package identities pin both hashes; preparation and runtime verify the exact archive-derived payload set. |
| FileInfo reports sandbox symlink length | Archive validation measures the opened stream; real symlink and forged-manifest controls exercise the boundary. |
| SDK resolution masks a failed restore marker | Successful restore is checked before resolution; dependency snapshots are still checked after implicit references resolve. |

The relevant implementation is in GraphExport, prepare_graph.py, graph_packages.py,
PackageInputs and the SDK repository rule. [Input discovery](input-discovery-findings.md),
[Nix imports](nix-sdk-import-findings.md) and [package policy](serilog-inputs-findings.md)
record the detailed boundaries. Failed intermediate runs are retained as evidence;
acceptance refers to the later successful runs only.

## Qualification boundary

Linux validation is [deferred by request](platform-validation-scope.md). This is
native macOS ARM64, pinned SDK 10.0.100, Release/net10.0, selected-library acceptance.
It does not establish full Serilog test-project support, general analyzer/build
packages, arbitrary discovery hooks, RID/native package assets, useful performance,
cross-platform cache reuse, remote-cache correctness or full host closure.

The next bounded pilot extension is described in [API/test followup](serilog-approval-next.md).
The standalone API comparison is implemented; unchanged upstream Test execution
still requires separately qualified test-platform packages, generated test sources,
data lookup and runtime assets. R05 generator/reference-role work can build on
this measured input slice without claiming those broader test contracts.
