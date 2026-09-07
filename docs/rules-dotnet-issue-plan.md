# Upstream issue lessons and adapter coverage plan

Snapshot: 2026-09-07 against adapter main `5e78487`.
Integration updated to main `f6aa809`; upstream issue states retain the original snapshot.

We enumerated **38 open and 207 closed issues**, excluding pull requests, from
[bazel-contrib/rules_dotnet](https://github.com/bazel-contrib/rules_dotnet/issues).
The [complete inventory](rules-dotnet-issue-inventory.json) records issue URLs,
states, timestamps and every open issue's owner/acceptance requirement. All closed
items were screened by topic and discussion excerpts; the selected histories below
received deeper discussion/timeline/linked-PR review. This is planning evidence,
not an execution of upstream repros or proof that our adapter fixes them.

Retaining SDK/MSBuild targets avoids separately recreating their semantics, but
we still have to discover their inputs, stage their outputs and validate replay.
Do not import upstream workarounds such as disabling analyzers, flattening content,
changing target frameworks or falling back to unsandboxed execution. Use ordinary
MSBuild as the oracle, including when it intentionally rejects a package layout.

## Next batch and release gates

The selected `starlark_packages`, `starlark_configured` and `starlark_tests`
gates now have [native macOS qualification](r02-r04-validation-findings.md), landed
after this inventory began. Preserve that completion evidence. The cases below
are additional issue-derived extensions, to be checked against existing assertions
and qualified separately; R05 remains the next feature slice:

1. **R02 package validation:** meta-packages with transitive assemblies; mixed
   managed/native files; consumer-specific compile/runtime selection. Seed cases
   from #413 and #508, retaining package upgrade, PrivateAssets and missing-input
   controls. Existing managed-package evidence is a starting point, not these repros.
2. **R03 configuration validation:** mixed TFM runtime selection, implicit usings,
   discovery refresh and tool/application configuration separation (#523/#436/#468).
   The mixed-TFM case must run the API after recovery, not merely compile.
3. **R04 test validation:** changed test code must really execute, runner/adapter
   version changes must invalidate, and nested plugin/data layout must survive
   producer deletion (#109/#207/#450). Existing Serilog acceptance remains scoped.
4. **R05 generator/resource extension:** SDK/package generator conflicts,
   implementation-versus-reference roles, transitive generator dependencies,
   embedded resource names and culture satellites (#467/#471/#474/#466).
5. **R06/R07 acquisition and output contracts:** local feeds/Pack consumers;
   CPM/locked restore/source configuration; native assets; content layout and
   ordinary Publish. Author local feed fixtures before using external credentials.

The newly explicit `test_coverage` gate extends R04 after `starlark_tests`. Coverage
is not established by a passing test suite. It requires a pinned collector,
transitive symbols, actual instrumented execution and source-mapped report checks.
It may remain an explicit release exclusion, but cannot disappear into generic
"test support." Fable integration remains explicitly deferred. R17 must disposition
both before selecting a supported release scope.

Later R10/R11/R15 retain web, Windows/language and IDE ownership. R13/R14 own
independent-worker cache/execution; local Linux container evidence cannot satisfy
those gates. R17's Bazel compatibility gate adds fetch/mod-deps, lockfile stability,
execution groups and external consumer/provider checks before any supported release.
These are extra acceptance cases, not new passing milestone statuses. Existing
platform scope remains unchanged by this review.

## Every open issue: owner and required evidence

Owner names refer to the [roadmap DAG](roadmap-graph.json). Each row is an unmeasured
extension unless a linked findings record later establishes the exact case. Some
open issues already reference merged PRs; board state alone does not prove either
absence or completeness of upstream support.

| Issue / concern | Owner | Planned acceptance or scope decision |
| --- | --- | --- |
| [#532](https://github.com/bazel-contrib/rules_dotnet/issues/532) ICU dependency | R07/R14: `native_assets`, `worker_closure` | Declare and verify ICU and loader dependencies; culture-sensitive execution on a clean worker; missing ICU fails. Invariant mode is a separate opt-in contract, not a substitute. |
| [#530](https://github.com/bazel-contrib/rules_dotnet/issues/530) NuGet resolver | R07: `restore` | Use ordinary per-project NuGet restore and consumer assets, not a replacement repository-wide resolver. Lock-mode and conflicting per-project resolutions must match MSBuild. |
| [#527](https://github.com/bazel-contrib/rules_dotnet/issues/527) NuGet package creation | R06: `pack` | Run SDK Pack, inspect nuspec and payload, restore into a fresh independent consumer, build and execute; repeat after package input mutation. |
| [#526](https://github.com/bazel-contrib/rules_dotnet/issues/526) Web configuration at launch | R10: `web` | Launch recovered web output from a different working directory; read environment-specific appsettings and assert the same values as the ordinary SDK baseline. |
| [#525](https://github.com/bazel-contrib/rules_dotnet/issues/525) Windows argument escaping | R11: `desktop` | Echo arguments exactly through run/test/tool launchers: spaces, empty values, quotes, backslashes, trailing slash and Unicode; retain exit codes. |
| [#524](https://github.com/bazel-contrib/rules_dotnet/issues/524) Compiler options referencing files | R05: `generators` | Preserve evaluated compiler/task file inputs, including response/config/additional files; mutation invalidates the consumer and missing data fails. No $(location) API is promised for csproj properties. |
| [#523](https://github.com/bazel-contrib/rules_dotnet/issues/523) Mixed-framework runtime selection | R03/R07: `starlark_configured`, `restore` | App and library select different compatible TFMs; compare per-consumer compile/runtime assets and execute the disputed API after recovery. Add F# variant in R11. |
| [#519](https://github.com/bazel-contrib/rules_dotnet/issues/519) Generated internals in public docs | R17: `dispositions` | Separate supported generated/provider APIs from internal modules in documentation; validate examples against the release. Paket-specific docs are not an adapter feature. |
| [#508](https://github.com/bazel-contrib/rules_dotnet/issues/508) Native DLL accidentally used as managed reference | R02/R04: `starlark_packages`, `starlark_tests` | Pin a TestHost-shaped package containing managed and native DLLs; use SDK-selected references, retain native payload roles, and discover/run tests without CS0009. |
| [#490](https://github.com/bazel-contrib/rules_dotnet/issues/490) Flattened content directories | R07/R10: `publish`, `web` | Preserve SDK TargetPath/Link and copy metadata, nested files and duplicate basenames. Build/Publish/Launch oracles must read original relative paths. |
| [#484](https://github.com/bazel-contrib/rules_dotnet/issues/484) Native AOT | R08: `aot` | Execute recovered native Publish output without an installed managed runtime; mutate/reject compiler, linker and runtime packs. |
| [#477](https://github.com/bazel-contrib/rules_dotnet/issues/477) Framework modules versus assemblies | R11: `desktop` | Distinguish Framework wrapper/module inputs from compiler references using ordinary SDK results; build and run the selected net48 slice. PR506 merged, but the issue remains open. |
| [#476](https://github.com/bazel-contrib/rules_dotnet/issues/476) Fetch triggers configuration analysis | R17: `bazel_compatibility` | Test fetch, mod deps, query, cquery and build in a fresh generated workspace on every supported Bazel version; fetch must not depend on an incidental consumer transition. |
| [#468](https://github.com/bazel-contrib/rules_dotnet/issues/468) Bootstrap tool coupled to application SDK | R03/R17: `entrypoints`, `bazel_compatibility` | Pin exporter/runner tool requirements separately from requested application TFM; support or clearly reject SDK overrides before publication. Paket implementation is out of scope. |
| [#467](https://github.com/bazel-contrib/rules_dotnet/issues/467) Duplicate SDK/package generators | R05: `generators`, `interceptors` | Use SDK plus package Binder generators and different versions; capture the exact analyzer closure and generated diagnostics, with duplicate/missing-dependency negative cases. |
| [#466](https://github.com/bazel-contrib/rules_dotnet/issues/466) Localization and satellites | R05/R07: `generators`, `publish` | Compile neutral and culture-specific resx through MSBuild; assert manifest names and ResourceManager fallback, then mutate and recover satellites. PR548 is open, not accepted upstream evidence. |
| [#457](https://github.com/bazel-contrib/rules_dotnet/issues/457) Automatic execution groups | R17: `bazel_compatibility` | Exercise applicable execution-group defaults/flags and tool assignment on selected Bazel versions; do not blanket-disable incompatibilities to pass. |
| [#450](https://github.com/bazel-contrib/rules_dotnet/issues/450) Plugin DLL locations in tests | R04/R07: `starlark_tests`, `publish` | Test assembly loads plugins from a nested path relative to itself; compare ordinary SDK output and recovered staging, and reject missing plugins. |
| [#446](https://github.com/bazel-contrib/rules_dotnet/issues/446) Reopened package-tool path error | R03: `entrypoints` | Fresh bootstrap/export from empty, missing and relocated input paths must report actionable errors without publishing a partial graph; do not port paket2bazel. |
| [#444](https://github.com/bazel-contrib/rules_dotnet/issues/444) Central Package Management and locks | R07: `restore` | Declare Directory.Packages.props, NuGet.config and per-project locks; mutate central versions/conditions, test locked-mode rejection, and distinguish NuGet content hashes from archive/payload digests. |
| [#442](https://github.com/bazel-contrib/rules_dotnet/issues/442) CLI tools used during builds | R06: `tasks` | Stage a package-delivered tool and all dependencies; produce and consume an extra XmlSerializers-like assembly in a fresh sandbox. PR516 adds upstream tool support, not proof of this exact MSBuild target. |
| [#436](https://github.com/bazel-contrib/rules_dotnet/issues/436) Implicit usings | R03/R05: `starlark_configured`, `generators` | Keep SDK-generated GlobalUsings; toggle ImplicitUsings and custom Using items across plain/web SDK baselines, checking compiler inputs and observable build outcome. |
| [#431](https://github.com/bazel-contrib/rules_dotnet/issues/431) Plain HTTP feed | R07: `restore` | Explicit local HTTP feed fixture under the pinned NuGet policy; validate acquisition and package hashes, or reject clearly when policy disallows it. Never disable integrity globally. |
| [#423](https://github.com/bazel-contrib/rules_dotnet/issues/423) Assembly version metadata | R05/R06: `generators`, `git_tasks` | Inspect generated AssemblyInfo and reflected assembly/file/informational versions; mutate declared version inputs and custom generated source without duplicate attributes. |
| [#413](https://github.com/bazel-contrib/rules_dotnet/issues/413) Transitive meta-package exports | R02: `starlark_packages` | Empty meta-package leads to a transitive compile/runtime assembly; match NuGet closure without imposing strict-deps semantics on an ordinary csproj. |
| [#401](https://github.com/bazel-contrib/rules_dotnet/issues/401) Resolved package download URLs | R07: `restore` | Exercise nonstandard feed endpoints and redirects through NuGet; preserve source identity and content digests, without guessing URL shapes or leaking credentials. |
| [#391](https://github.com/bazel-contrib/rules_dotnet/issues/391) Library publishing | R07: `publish` | Qualify Publish on a library separately from executable Publish; compare SDK artifacts and use them in a fresh loader/consumer. |
| [#388](https://github.com/bazel-contrib/rules_dotnet/issues/388) NuGet build-folder semantics | R06/R07: `tasks`, `restore` | Preserve props/targets plus tools/data under build, buildTransitive and buildMultiTargeting; execute selected targets and reject missing tools rather than globbing DLLs as references. |
| [#379](https://github.com/bazel-contrib/rules_dotnet/issues/379) Artifactory and NuGet v2 endpoints | R07: `restore` | Local feed/proxy fixture for v2/v3, path prefixes, trailing slashes, redirects and authentication; test request failures and cache reuse with acquisition outside build actions. |
| [#359](https://github.com/bazel-contrib/rules_dotnet/issues/359) Coverage collection | R04 extension: `test_coverage` | New explicit gate: preserve collector/test-adapter and transitive PDB inputs, run instrumented tests after recovery, compare named covered/uncovered lines and emit a validated Bazel-consumable report. |
| [#358](https://github.com/bazel-contrib/rules_dotnet/issues/358) Single-file publishing | R07: `publish` | Separate framework-dependent/self-contained single-file fixtures; assert bundle contents, extraction behavior and execution without producer directories. |
| [#349](https://github.com/bazel-contrib/rules_dotnet/issues/349) Native dependencies | R07: `native_assets` | P/Invoke with native package and source-built library variants; verify selected RID, loader dependencies, actual execution and rejection after removal. |
| [#315](https://github.com/bazel-contrib/rules_dotnet/issues/315) F# source provider for Fable | R11/R17: `desktop`, `dispositions` | Ordinary F# compilation gets a named lane; Fable/source-provider API is explicitly deferred until a consumer contract is selected. Do not infer support from DLL providers. |
| [#258](https://github.com/bazel-contrib/rules_dotnet/issues/258) Automatic build generation | R03/R15: `starlark_configured`, `design_time` | Regenerate from unchanged csproj semantics; new globs/imports/references update graph deterministically. Developer command and diagnostics need a clean-checkout usability check. |
| [#249](https://github.com/bazel-contrib/rules_dotnet/issues/249) Razor and Blazor | R10: `web` | Retain Razor targets, generated editorconfig metadata, static web assets and runtime compilation context; qualify server and WASM separately with fresh/recovered browser execution. |
| [#228](https://github.com/bazel-contrib/rules_dotnet/issues/228) Debugging generated PDBs | R15: `design_time` | Breakpoints and source mapping must work after relocation using declared PDB/SourceLink/source-map policy; sandbox retention is not an acceptable dependency. |
| [#207](https://github.com/bazel-contrib/rules_dotnet/issues/207) Hardcoded test runner versions | R04: `starlark_tests` | Resolve and pin runner/adapter versions from the selected project contract; upgrade one deliberately and verify test identities, failure propagation and cache invalidation. |
| [#124](https://github.com/bazel-contrib/rules_dotnet/issues/124) Local package feeds | R06/R07: `pack`, `restore` | Restore checked-in and newly packed nupkg files through a declared local feed into an empty consumer cache; path/version/content mutation and missing package controls. |

## Closed histories: what changed and what to retain

“Maintainer reports fixed” records the discussion, not a verified release test.
“Workaround,” “configuration” and “retired scope” are deliberately separate from
merged implementation fixes. Links to PRs below were checked for merge state.

| History | Observed resolution and limits | Adapter regression / owner |
| --- | --- | --- |
| [#443](https://github.com/bazel-contrib/rules_dotnet/issues/443), [#447](https://github.com/bazel-contrib/rules_dotnet/issues/447) | Analyzer/source-generator handling was reworked in merged [PR452](https://github.com/bazel-contrib/rules_dotnet/pull/452). Open #467 reports an SDK/package duplication case after that fix. | R05: generated output and diagnostics, distinct reference/analyzer roles, duplicate SDK/package versions; never count “generator support” as one boolean. |
| [#471](https://github.com/bazel-contrib/rules_dotnet/issues/471) | Merged [PR473](https://github.com/bazel-contrib/rules_dotnet/pull/473) supplies analyzer dependencies using implementation DLLs. Its description explicitly limits automatic discovery to one level. | R05: multi-level dependency chain and an assembly used both normally and by a generator; remove one analyzer dependency to prove load failure. |
| [#414](https://github.com/bazel-contrib/rules_dotnet/issues/414), [#346](https://github.com/bazel-contrib/rules_dotnet/issues/346) | Merged [PR419](https://github.com/bazel-contrib/rules_dotnet/pull/419) added a run-analyzers option. Disabling analyzers was a workaround for the web compile error. | R05/R10: preserve the project's analyzer settings and required generated functionality; successful compilation with generators disabled does not qualify the original app. |
| [#465](https://github.com/bazel-contrib/rules_dotnet/issues/465) | Reporter identified a missing dependency; a separate version issue was linked to PR470. This is not evidence that all SDK analyzer selection was repaired. | R05: missing analyzer dependency has an exact failure oracle; selected package and SDK versions are recorded. |
| [#474](https://github.com/bazel-contrib/rules_dotnet/issues/474) | Merged [PR475](https://github.com/bazel-contrib/rules_dotnet/pull/475) changed embedded resource naming. Later comments still discuss RootNamespace and LogicalName nuances. | R05: inspect manifest names for nested resources, explicit LogicalName, differing namespace/assembly names and linked files; use evaluated MSBuild metadata. |
| [#493](https://github.com/bazel-contrib/rules_dotnet/issues/493) | Maintainer reports a fix after a package's incomplete resource-assembly TFM map selected incorrectly. The proposed workaround added an empty net6.0 resource set. | R03/R07: distinguish an intentionally empty asset group from absent compatibility information; run selected runtime and satellite assets. |
| [#405](https://github.com/bazel-contrib/rules_dotnet/issues/405) → open [#477](https://github.com/bazel-contrib/rules_dotnet/issues/477) | Initial special-casing of Framework DLLs led to another failure. Merged [PR506](https://github.com/bazel-contrib/rules_dotnet/pull/506) keeps wrapper files as inputs while excluding them from compiler references. | R11: validate file roles against SDK resolution, not a blanket DLL glob or filename deletion. An open issue can have a merged partial fix. |
| [#434](https://github.com/bazel-contrib/rules_dotnet/issues/434) | Merged [PR438](https://github.com/bazel-contrib/rules_dotnet/pull/438) adds publish appsettings support. Open #526 and #490 expose distinct launch/content-layout concerns. | R07/R10: test Build, Publish and Launch separately, with nested data and a changed working directory. |
| [#430](https://github.com/bazel-contrib/rules_dotnet/issues/430), [#422](https://github.com/bazel-contrib/rules_dotnet/issues/422), [#320](https://github.com/bazel-contrib/rules_dotnet/issues/320), [#317](https://github.com/bazel-contrib/rules_dotnet/issues/317) | Discussions report fixes for RID output layout, conflicting runtimeconfig fields, target apphost packs and the missing binary entry in deps.json. | R07: separately inspect target RID versus host, requested runtime version/roll-forward, apphost and deps/runtimeconfig; execute recovered publish output. |
| [#505](https://github.com/bazel-contrib/rules_dotnet/issues/505) | Reporter says a self-contained publish variant works for RocksDB; this does not establish ordinary binary/test native loading. | R07: native library loading in Build/Test/Publish must each be measured; do not substitute Publish for a failing Test contract. |
| [#501](https://github.com/bazel-contrib/rules_dotnet/issues/501) | Web-SDK tests lacked ASP.NET runtime dependencies on remote workers. Issue comments report a fix on master. Referenced [PR502](https://github.com/bazel-contrib/rules_dotnet/pull/502) describes copying them, but its API merge timestamp is null; it is not recorded here as a merged PR. | R04/R14: web test runs with only declared SDK/runtime files on the worker; ambient installed .NET cannot repair an incomplete closure. |
| [#537](https://github.com/bazel-contrib/rules_dotnet/issues/537) | Discussion moved from suspected platform selection to image output layout; a publish-to-tar workaround succeeded. A later comment links a rules_img change to include executable DefaultInfo files. | R07/R12: image composition preserves complete output tree and target architecture. Diagnose actual missing artifacts rather than trusting the issue title. |
| [#347](https://github.com/bazel-contrib/rules_dotnet/issues/347), [#36](https://github.com/bazel-contrib/rules_dotnet/issues/36) | Discussions report repairs to binary-as-tool dependency resolution and working-directory behavior. | R06/R12: use the built tool from another action with runfiles, dependencies and declared data; assert output, arguments and exit code. |
| [#109](https://github.com/bazel-contrib/rules_dotnet/issues/109), [#100](https://github.com/bazel-contrib/rules_dotnet/issues/100) | #109 identified an existing hardlink being treated as successful staging, leaving tests executing stale DLLs; its close event references commit bfa872b. #100 reports cross-filesystem hardlink failures. The linked “remove hardlinks” PR111 is closed without a merge timestamp. | R01/R04/R06: replace an existing staged test binary and require changed behavior; recover into a fresh filesystem/output location without depending on hardlink availability. |
| [#296](https://github.com/bazel-contrib/rules_dotnet/issues/296) | Compiler outputs contained sandbox paths. Maintainer reports path-mapping wrappers in v0.8.4; a lingering failure was traced to a user's repository override. | R01/R09/R13: force fresh executions at different roots, compare DLL/PDB/bundle bytes and permissions, and isolate user Bazel configuration. Existing staging evidence covers only its named C# slice. |
| [#415](https://github.com/bazel-contrib/rules_dotnet/issues/415) | Issue closed as fixed after transition/debugging discussion and removal of Paket dependencies from a data attribute. | R03/R09: inspect configured action multiplicity; distinguish legitimate distinct configurations from accidental repeated generator work. |
| [#486](https://github.com/bazel-contrib/rules_dotnet/issues/486) | Merged [PR489](https://github.com/bazel-contrib/rules_dotnet/pull/489) marks NuGet extensions reproducible to reduce cross-platform lock churn. | R17: shared checkout lockfile checks on each supported platform; annotate reproducibility only when repository inputs support that claim. |
| [#458](https://github.com/bazel-contrib/rules_dotnet/issues/458), [#322](https://github.com/bazel-contrib/rules_dotnet/issues/322), [#364](https://github.com/bazel-contrib/rules_dotnet/issues/364) | Empty-glob behavior and host-transition changes required compatibility work; #364 identifies a Bazel-side transition fix. | R17: named Bazel-version/incompatibility matrix, platform-specific SDK globs, fetch/query and actual actions. Not every failure belongs in adapter code. |
| [#378](https://github.com/bazel-contrib/rules_dotnet/issues/378), [#371](https://github.com/bazel-contrib/rules_dotnet/issues/371), [#361](https://github.com/bazel-contrib/rules_dotnet/issues/361) | Discussions report v2 URL, slash handling and private-feed support changes. Open #379/#401/#431 show additional acquisition cases. | R07: a local protocol fixture exercises source discovery, URL prefixes and authenticated acquisition; no credentials in manifests/logs or build actions. |
| [#448](https://github.com/bazel-contrib/rules_dotnet/issues/448), [#461](https://github.com/bazel-contrib/rules_dotnet/issues/461) | #448 was closed because root-lib behavior matched PackageReference semantics. #461 was closed with local-file sources described as unsupported. Neither is a new compatibility implementation. | R07/R11: distinguish PackageReference from packages.config; local feeds remain an explicit adapter feature to test. |
| [#418](https://github.com/bazel-contrib/rules_dotnet/issues/418) → [#446](https://github.com/bazel-contrib/rules_dotnet/issues/446) | A claimed package-tool fix was followed by a reproducible report and a new open issue. | R03/R17: keep exact repro inputs/platform/tool versions and negative bootstrap tests after closing a bug. |
| [#469](https://github.com/bazel-contrib/rules_dotnet/issues/469), [#441](https://github.com/bazel-contrib/rules_dotnet/issues/441), [#341](https://github.com/bazel-contrib/rules_dotnet/issues/341), [#125](https://github.com/bazel-contrib/rules_dotnet/issues/125) | xUnit discussion supplies a custom-runner example; other discussions report test env, renamed outputs and data-attribute support. #125 explicitly leaves runfiles placement as a separate issue. | R04: native test discovery, exact identities/counts, failures, env, renamed assembly and data; fresh test execution after build-cache recovery. |
| [#337](https://github.com/bazel-contrib/rules_dotnet/issues/337), [#456](https://github.com/bazel-contrib/rules_dotnet/issues/456) | Merged [PR516](https://github.com/bazel-contrib/rules_dotnet/pull/516) adds NuGet tool execution; #456 links a change exposing package contents. | R06: SDK-pinned tool actions and complete package tools/data closure; MSBuild target integration remains a separate step. |
| [#500](https://github.com/bazel-contrib/rules_dotnet/issues/500) | Early comments called .fsi unsupported; merged [PR556](https://github.com/bazel-contrib/rules_dotnet/pull/556) later allowed F# interface files. | R11: preserve ordered .fsi/.fs inputs and sidecar/compiler dependencies; validate current code rather than carrying an old comment forward. |
| [#400](https://github.com/bazel-contrib/rules_dotnet/issues/400), [#345](https://github.com/bazel-contrib/rules_dotnet/issues/345), [#344](https://github.com/bazel-contrib/rules_dotnet/issues/344), [#343](https://github.com/bazel-contrib/rules_dotnet/issues/343), [#389](https://github.com/bazel-contrib/rules_dotnet/issues/389) | Discussion records existing language-version support and additions/repairs for warning policy, XML docs and roll-forward. | R03/R05/R07: declared properties affect outputs/diagnostics and action identity; generated XML docs and runtime policy belong in the output contract. |
| [#385](https://github.com/bazel-contrib/rules_dotnet/issues/385) → [#532](https://github.com/bazel-contrib/rules_dotnet/issues/532), [#221](https://github.com/bazel-contrib/rules_dotnet/issues/221) | The #221 discussion reports missing shared-runtime inputs repaired by PR224. ICU is still an open hermetic-input concern in #532 despite the older #385 closure. | R13/R14: fail closed on missing runtime closure; local setup success or an installed system library is not independent-worker evidence. |
| [#440](https://github.com/bazel-contrib/rules_dotnet/issues/440), [#145](https://github.com/bazel-contrib/rules_dotnet/issues/145), [#14](https://github.com/bazel-contrib/rules_dotnet/issues/14), [#140](https://github.com/bazel-contrib/rules_dotnet/issues/140) | Examples of retirement of WORKSPACE/Mono scope and inactivity closures. | R17: name exclusions and supported versions. Closing a report does not establish a working behavior. |

Older release, documentation, legacy toolchain, duplicate and historical example
issues remain searchable in the complete inventory. They inform R17's clean-user
setup, supported-version and documentation gates; this review does not promise
support for every discontinued .NET/Mono/Bazel version. Deeper code archaeology
for a historical failure is required when a new supported slice actually depends
on it.

## Completion rules and refresh

For each adopted row, create a small pinned fixture or pin a usable upstream
repro, record an ordinary SDK oracle, and add baseline/mutation/missing-input/
producer-free recovery assertions applicable to its operation. Capture diagnostics
and actual action/test execution. Extend S01–S05 as appropriate; no row becomes
measured solely because an adjacent milestone already passed. Record unsupported
variants explicitly before running the experiment.

The review used the paginated GitHub REST `/repos/bazel-contrib/rules_dotnet/issues`
endpoint with `state=all&per_page=100`, excluded entries with `pull_request`, and
joined the paginated repository `issues/comments` endpoint by issue number.
Selected `issues/{number}/timeline` and `pulls/{number}` responses were inspected
for the histories above. Inventory counts and open-owner completeness were checked
locally; no upstream code was executed and no issues/comments were posted.

To refresh the inventory inputs (read-only):

```sh
gh api --paginate 'repos/bazel-contrib/rules_dotnet/issues?state=all&per_page=100' --slurp > /tmp/rules-dotnet-issues.json
gh api --paginate 'repos/bazel-contrib/rules_dotnet/issues/comments?per_page=100' --slurp > /tmp/rules-dotnet-comments.json
```

Then filter PR entries, compare issue numbers/states/updated timestamps with the
checked-in inventory, read changed discussions and closure evidence, and revise
owners/acceptance rows. Counts are a dated snapshot, not an ongoing monitor.
