# API

Start with the [quick start](../examples/quickstart/README.md). Load rules from `@rules_msbuild//msbuild:defs.bzl`, sync from `@rules_msbuild//msbuild:sync.bzl`, and SDK declarations from `@rules_msbuild//msbuild:sdk.bzl`. See [Design](design.md) for ownership and invalidation.

## Pin, update and roll back the rules

Distribution is a pinned source revision (no published Bazel module release). In root `MODULE.bazel`, pin a reviewed full Git commit and register SDK toolchains as in the quick start:

```starlark
bazel_dep(name = "rules_msbuild", version = "0.0.0")
git_override(
    module_name = "rules_msbuild",
    remote = "https://github.com/keegan-caruso/msbuild-bazel.git",
    commit = "REPLACE_WITH_FULL_REVIEWED_COMMIT",
)
```

`0.0.0` is a placeholder, not a release/compatibility promise; the commit selects the source. Commit both the pin and `MODULE.bazel.lock`. On update: refresh/review the lockfile, run sync, review generated graph changes, and validate builds/tests. On rollback: restore the previous commit, lockfile, and matching generated declarations, then rerun checks. Keep the revision reachable via its Git remote or mirror.

API, contracts, runner, and project-cache format may change between commits (no cross-revision compatibility guarantee; Bazel action keys and project-cache fingerprints do not guarantee every revision change invalidates every entry). Until a compatibility policy exists, use separate action and project-cache namespaces/endpoints per reviewed rules revision and keep the old namespace for rollback (operational recommendation, not automatic enforcement). Keep SDK, Bazel, and package pins with each reviewed consumer state.

## Sync

```starlark
msbuild_sync(name = "sync", projects = ["App/App.csproj"])
```

Run `bazel run //:sync`; commit `graph.generated.json` and `graph.generated.bzl` (exposes `app_graph`). Body edits build normally; resync after project/import, package, configuration, or explicit source-list changes. `bazel run //:sync -- --check` rejects stale declarations.

`projects = ["App.sln"]` (or `.slnx`) works for update and sync: MSBuild expands the solution keeping config mappings, build exclusions, and solution-only deps; the solution is hashed/staged and derived absolute solution globals regenerate for the current workspace. One solution per target; mixed entries, `.slnf`, custom solution build hooks, and overrides of derived solution globals are unsupported.

Sync can shorten C# lists with checked, nonrecursive globs when shorter (retaining expected filenames: membership changes require sync, body edits build normally). To allow add/remove without sync, pass `mappings = "mappings.json"` with reviewed Compile-only patterns per affected configuration:

```json
{"projects":{"Library/Library.csproj":{"compileGlobs":["Library/Sources/**/*.cs"]}}}
```

Patterns are workspace-relative `directory/*.cs`, `directory/**/*.cs`, `*.cs`, or `**/*.cs`. Recursive patterns include new subdirectories and exclude `bin`, `obj`, `bazel-*`, and hidden dirs. Bazel declares current members; the contract records the pattern; sync/builds verify Compile-only selection. Membership must affect only compilation (Restore, imports, project refs stay independent). Unsupported: hidden files, symlinks, generated/bound inputs, nested Bazel packages, custom exclusions, and arbitrary owned output dirs inside recursive patterns. Files outside patterns still require sync. Root projects need an authored `NuGet.Config` and must exclude `bazel-*/**/*.cs` from MSBuild Compile items.

| Attribute | Use |
| --- | --- |
| `projects` | Project paths (`.csproj`, `.vbproj`, `.fsproj`, `.ilproj`, Traversal/NoTargets `.proj`) or one `.sln`/`.slnx` |
| `srcs` | Optional complete authored snapshot making sync preparation a cacheable Bazel action |
| `configuration`, `framework` | Default `Release`; optional entry framework |
| `inputs` | Single-file or directory-tree producer labels mapped to workspace-relative paths |
| `build_inputs` | Same bindings with bytes used only by Build; requires `preparedRestore` |
| `package_lock`, `package_locks` | Closed package inventories, including package SDKs |
| `package_build`, `package_inputs` | Offline Restore/package evaluation (defaults on with closed package inventory or complete `srcs`; extra task reads remain explicit) |
| `resolve_references` | Defaults on with `package_build`; private Build captures compiler/copy selections at supported boundaries |
| `qualification_cache` | Auto-enabled with complete `srcs`, reference qualification, qualified execution platform, and HTTP project cache |
| `seed_build_cache` | Defaults on with eligible `qualification_cache`; consumers need matching Linux stable paths |
| `bindings` | Complete tool layouts bound to MSBuild properties |
| `mappings` | Reviewed JSON contracts for custom inputs, outputs, and dependency roles |

Assembly `Reference` items may use a `HintPath` or relative `Include` from `inputs` (sync records label/path; builds hash the DLL). Bound trees keep one producer edge and declare all member bytes as shared inputs (membership changes require resync; `inputDirectories` alone declares presence; internal symlinks and authored-path collisions fail).

`build_inputs` declares Restore needs only names/directory presence, not contents: Restore materializes empty files in the committed layout while Build hashes real producer bytes (preserving `Exists()` and globs without invalidating Restore on API edits). Membership changes require resync. Imports, explicit Restore inputs, and package-task reads cannot use `build_inputs` (use `inputs` for content/metadata reads; sync does not trace arbitrary task reads).

Unbound workspace/host assembly paths fail. Same-repo sources stage relative to that repo; cross-repo producers require `input_paths`.

Traversal/NoTargets/IL/Arcade require locking the SDK and implicit/native packages plus declaring custom tasks/products. Closed inventories enable package evaluation; unknown SDKs fail. See [qualified SDKs](support.md#qualified-sdks).

### Compiler selections

Closed sync (package inventory or complete `srcs`) runs offline Restore and Build by default in a disposable workspace, capturing SDK-selected DLLs and copy sources at supported C# reference boundaries (multi-target uses configured producer ownership). Failures, undeclared inputs, ambiguous producers, or conflicting manual bindings leave existing contracts intact. Builds consume the contract; default `--check` repeats qualification.

To reuse preparation across sync and check, declare the complete workspace:

```starlark
msbuild_sync(
    name = "sync",
    projects = ["src/App/App.csproj"],
    srcs = glob(
        ["src/**", "*.props", "*.targets", "global.json", "NuGet.Config",
         ".editorconfig", "**/.editorconfig", ".globalconfig", "**/.globalconfig"],
        exclude = ["**/bin/**", "**/obj/**"],
        allow_empty = True,
    ),
)
```

`srcs` defines everything MSBuild sees (include imports, data, locks, implicit configs; omit generated declarations and build outputs; declare cached sync and its sources in the main workspace root package; use `inputs`, `build_inputs`, and `bindings` for generated artifacts/tools; empty authored dirs cannot be represented). Bazel keys preparation on `srcs`, SDK/runner, settings, mappings, packages, and producers. The launcher accepts only `--check` (change other settings in the target). Publication protects authored files and checks both declarations before replacing either. NuGet update remains a separate resolving command.

Closed sync reuses individual projects after source edits when `--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=http://cache:8080` is set (optional `RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN` via `--action_env`). Requires Linux with `/usr/bin/bwrap`, user namespaces, and the qualified execution image declared on the **execution** platform (SDK toolchain must also support it). Add `bazel_dep(name = "platforms", version = "1.0.0")` to `MODULE.bazel` if absent, then in root `BUILD.bazel`:

```starlark
platform(
    name = "qualified_linux",
    constraint_values = [
        "@platforms//os:linux",
        "@platforms//cpu:aarch64",
        "@rules_msbuild//msbuild:qualified_linux_bwrap",
    ],
)
```

Select via `--extra_execution_platforms=//:qualified_linux` (target-platform OS constraint alone does not enable it; optional capability toolchain registers automatically). Missing capability/endpoint falls back to ordinary qualification. Explicit `qualification_cache = True` forces Linux/bwrap and rejects missing inputs/endpoint; `False` disables automatic options. No endpoint is inferred from Bazel's remote cache.

Package/tool runfiles materialize before entering a fixed private namespace; authored sources are read-only; publication runs after qualification succeeds. Keys use pre-contract evaluated inputs (SDK/runner bytes, declared inputs, package archives, Restore assets, targets, conservative dep source/product hashes); hits restore verified owned artifacts and SDK compiler/copy metadata. Restore has its own verified snapshot (evaluation stays fresh; by default all source contents invalidate Restore unless exempted via root `restoreReuseInputs`). Misses run normal SDK Build; shared inputs invalidate affected keys; overlapping output owners and consumers skip reuse. Does not infer precise reference boundaries before qualification.

Eligible qualification also publishes ordinary Build snapshots to the same HTTP cache (`seed_build_cache`, defaults on with declared execution capability; disable via `seed_build_cache = False`). Consumers auto-use stable paths on that execution platform (or set `linux_stable_paths = True`) with matching SDK, runner, config, and inputs. Qualification retains intermediate outputs; the ordinary runner verifies SDK/input/output bytes, evaluated properties/items, target results, and compiler selections, reusing verified Restore products with no second compilation (incompatible handoffs fail before declaration publication). Runs only when qualification executes (whole-action hits do not refill evicted project entries). See [qualified scope](support.md#project-qualification-cache).

For a packaging action that can run after a separate Build, set `reuse_build_cache = True` on `app_graph` or `msbuild_graph`. Rerun sync to add the option to an existing generated wrapper.

```starlark
app_graph(name = "package", target = "Pack", reuse_build_cache = True)
app_graph(name = "publish", target = "Publish", reuse_build_cache = True)
```

The first phase requests normal Build results. A matching project snapshot supplies its outputs, and a miss executes the project's Build. The second phase executes the requested SDK target with `NoBuild=true` in the same staged workspace. Bazel can cache the complete packaging action. Use a fresh non-worker graph and keep the configured project references and product paths stable across both phases. Place target-only products, such as the nupkg, under a declared output directory. The Build phase must produce every individually required `outputFiles` entry. This mode requires all Build intermediates, so it rejects contracts with replay omissions. The graph report records Build-phase reuse in `buildSeedHits` and `buildSeedMisses`.

Complete inventories exclude unselected compiler edges from invalidation while keeping graph execution and noncompiler dep roles. New snapshots verify `ReferencePathWithRefAssemblies`; SDK and declared package/file inputs keep byte hashes. Custom task reads and Pack/Publish-specific selections still need contracts; unsupported boundaries keep conservative keys.

### Mappings

Use `projectDefaults`, project-path `projects`, `frameworkOverrides`, and root `entryProperties` (graph-wide properties go in `projectDefaults.properties`). Unknown/duplicate fields, unsafe paths, and changed document attestations fail. With qualification caching, root `restoreReuseInputs` lists reviewed workspace-relative Compile files whose contents cannot affect Restore (names/modes stay keyed; definitions, explicit Restore inputs, and other files cannot be exempt; separate from `evaluationReuseInputs`).

| Contract fields | Purpose |
| --- | --- |
| `documents`, `inputItems`, `evaluationItems` | Attested target/task documents and extra reads |
| `inputDirectories`, `temporaryDirectories`, `outputFiles` | Input trees, private scratch, owned products |
| `preparedRestore`, `restoreInputs`, `restoreOutputs` | Separate Restore contract (inferred for closed standard SDK projects without package/custom hooks, or reviewed explicitly) |
| `referenceBoundary`, `implementationDependencies` | Qualified compiler boundary; conservative task/tool edges |
| `compilerReference`, `compilerReferences`, `compilerReferencesComplete` | Producer artifact, consumer selections, complete-inventory assertion |
| `dependencyCopies` | Consumer DLL/PDB/XML destinations mapped to graph/locked-package sources |
| `compileGlobs` | Reviewed C# source membership per configured project |
| `evaluationReuseInputs`, `replayOmissions` | Reviewed compiler-only inputs and disposable intermediates |

Existing workspace files named by reviewed `evaluationItems` are definition inputs for Build and prepared Restore (preserving glob membership outside the graph; scalars stay metadata).

Manual `compilerReferencesComplete: true` requires `referenceBoundary: true` and all SDK-selected project DLLs (partial maps keep conservative transitive keys). Implementation DLLs belong in `compilerReferences` when Csc reads them; extra task/tool reads belong in `implementationDependencies`.

`dependencyCopies` accepts MSBuild expressions (package sources require prepared Restore) and describes replay only (MSBuild still chooses build copies). Omitted files remain stored/verified in snapshots; required references, outputs, copies, and target-result paths cannot be omitted (qualified for Build only).

## Build and artifacts

| Rule | Use |
| --- | --- |
| `msbuild_graph_runner`, `msbuild_graph` | Runner bootstrap and graph targets (Build, Pack, Publish, DesignTimeBuild) |
| `msbuild_graph_binary`, `msbuild_graph_test` | Run/test a `project` (set `framework` if ambiguous) |
| `msbuild_graph_layout`, `msbuild_graph_output` | Export a layout, owned file, or directory tree |
| `msbuild_graph_layouts` | Merge selected configured project outputs in one action |
| `msbuild_runtime_layout` | Compose a shared framework and runtime metadata from declared producers |
| `msbuild_graph_restore` | Prepare offline Restore for a matching stable-path graph |
| `msbuild_tool`, `msbuild_file_binding`, `msbuild_native_tool` | Bind complete task/native-tool layouts |
| `msbuild_layout`, `msbuild_runtime` | Compose artifacts and describe an execution host |
| `msbuild_nuget_package`, `msbuild_generated_nuget_package` | Validate/extract acquired or produced packages |
| `msbuild_nuget_dependencies`, `msbuild_package_lock` | Declare closed package inventories |
| `msbuild_test_tool`, `msbuild_native_toolchain*` | Select package test tools and native toolchains |

Use `app_graph(name = "editor", target = "DesignTimeBuild")` to export compiler inputs for single-framework C# SDK projects. Run `bazel build //:editor` and read `bazel-bin/editor.graph/report.json`. Each entry in `projects` identifies a project by its workspace-relative path and global properties. It includes Compile items, resolved references, project references, compiler arguments, and defined constants. Resolve relative Compile paths from the staged project directory. Expand `{workspace}` to `bazel-bin/editor.graph/workspace` and `{sdk}` to the matching SDK root. Project assembly references can point to another entry's `targetPath` or `targetRefPath`; bind those to the source project. The target uses a fresh non-worker graph.

Graph and Restore targets expose their exec-configured tool in the `runner` output group (`bazel build TARGET --output_groups=+runner`).

`msbuild_native_toolchain_packages` assembles SHA-256-locked `.deb` inputs into a tool tree (using qualified Ubuntu host `dpkg-deb`). Pass a sorted `manifest` for exact file selection, or omit to retain files under `usr` and `etc` (`exclude_prefixes` supported while keeping copyright notices). `symlinks` declares post-install aliases without running package scripts; `archive = True` also emits a deterministic link-preserving USTAR tar in the `archive` output group. Missing files, dangling/escaping links, and path conflicts fail.

Batch project dirs for larger graphs (keys match generated `project_outputs`; values are layout dirs; shared destinations must have identical bytes):

```starlark
msbuild_graph_layouts(
    name = "application_layout",
    graph = ":build",
    projects = {
        "App/App.csproj|net10.0": ".",
        "Tools/Tool.csproj|net10.0": "tools",
    },
)
```

For a source-built runtime, select managed producers by the same keys and map native files to destination paths:

```starlark
msbuild_runtime_layout(
    name = "runtime_layout",
    graph = ":build",
    projects = ["CoreLib/CoreLib.csproj|net10.0", "Library/Library.csproj|net10.0"],
    native = {":coreclr": "shared/Microsoft.NETCore.App/10.0.0/libcoreclr.so"},
    version = "10.0.0",
    target_framework = "net10.0",
    target_framework_moniker = ".NETCoreApp,Version=v10.0",
    runtime_identifier = "linux-arm64",
)
```

Copies selected output dirs, writes `.deps.json`, runtime config, version, and provenance (computed contract hash), and rejects destination conflicts. `data` maps single-file labels to extra paths; `provenance` takes JSON build facts. Example omits the other assemblies/native files needed to run an app. Pass to `msbuild_runtime` or `rules_pkg`'s `pkg_tar` (see [source-runtime-app](../examples/source-runtime-app/README.md)).

Handwritten graphs pass `contract`, `srcs`, and optional `input_paths`, `bindings`, `packages`/`package_lock`; `source_root` strips a Bazel package prefix. Contracts key projects by path + global properties; `project_outputs`/`publish_outputs` map `project|framework` to `[directory, assembly_filename, output_type]`. See [attributes](../msbuild/graph.bzl).

### NuGet updates

```starlark
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_nuget_update")
msbuild_nuget_update(name = "update_packages", projects = ["App/App.csproj"])
```

Run `bazel run //:update_packages` after package, framework, central-version, or SDK changes. Resolves in a disposable copy using the declared SDK and root `NuGet.Config` hierarchy. Restore and graph evaluation isolate [user-profile settings](https://learn.microsoft.com/en-us/nuget/consume-packages/configuring-nuget-behavior), including Windows roaming/local application data. Writes native project locks (`packages.PROJECT.lock.json` with spaces→underscores in shared dirs, `packages.lock.json` otherwise; existing project-specific locks win; name collisions fail) and `nuget.lock.json` (failures leave existing locks intact). Commit both. `--check` re-resolves online and rejects stale locks.

HTTP responses cache in `<user-data>/rules-msbuild/nuget-http` (override via `-- --http-cache /abs/path`, disable via `-- --no-http-cache`). `-- --distdir /abs/archives` exports verified archives for Bazel `--distdir` (existing files must match hashes).

After first update, wire the inventory in `MODULE.bazel`:

```starlark
nuget = use_extension("@rules_msbuild//msbuild:nuget.bzl", "nuget")
nuget.lock(name = "nuget", lockfile = "//:nuget.lock.json")
use_repo(nuget, "nuget")
```

Set `msbuild_sync(..., package_lock = "@nuget//:packages")` and run `bazel run //:sync`. Bazel fetches committed archives with SHA256 verification (`@nuget//:archives` exposes `.nupkg` files). Builds/sync restore offline; native locks preserve per-framework selections and are declared build/Restore inputs. `archiveSha512` hashes whole archives (NuGet's `contentHash` may differ for signed packages and stays untouched).

Requirements/limits: unambiguous root config, public HTTP(S) V3 feeds, no source symlinks. NuGet applies nested configs, inheritance, disabled sources, and source mappings; used configs are hashed (`--check` detects config-only changes); configs outside copied workspace/private home fail. Unqualified: custom lock locations, authenticated feeds, workloads, other native package flows. Arbitrary task reads still need contracts. Each update resolves one config (pass matching `configuration`, `framework`, `mappings` to update and sync; uses `projectDefaults.properties`/`entryProperties`; Restore keeps all authored frameworks; conflicting shared-project locks fail—use separate workspaces). Traversal, NoTargets, IL (including pinned ILAsm/ILDasm), and Arcade SDKs resolve before Restore from `global.json` `msbuild-sdks` or inline SDK versions (only used SDK archives enter the inventory; commit coordinator locks; skipped projects or unresolved SDKs fail atomically; other package SDKs unqualified). For new workspaces, run update before declaring the extension or loading generated graphs.

Handwritten inventories remain available (`allow_multiple_versions = True` allows distinct versions). For Pack, export `.nupkg` and consume via `msbuild_generated_nuget_package`.

Root/nested `.editorconfig` and `.globalconfig` files discovered by the SDK are explicit compiler inputs (auto-discovery stops at workspace root; outside reads fail; byte edits need no sync).

Task/analyzer layouts must include dependencies/data:

```starlark
msbuild_graph_layout(name = "tasks_layout", graph = ":tasks_graph", project = "Tasks/Tasks.csproj")
msbuild_tool(name = "task", layout = ":tasks_layout", entry_point = "Tasks.dll")
msbuild_file_binding(name = "binding", tool = ":task", property_name = "TaskLocation")
```

Pass bindings to sync and the generated graph (content edits invalidate consumers; property/entry-point changes require sync). Use `msbuild_graph_output(directory = True)` + `input_paths` for produced trees (consumed files still need contract inputs). Prepared Restore exports use `Restore.Outputs` ownership. Exports reject links.

## SDKs

`dotnet.sdk` selects an exact `version` or resolves from `global_json`:

```starlark
dotnet = use_extension("@rules_msbuild//msbuild:extensions.bzl", "dotnet")
dotnet.sdk(name = "dotnet", global_json = "//:global.json")
use_repo(dotnet, "dotnet")
register_toolchains("@dotnet//:all")
```

First resolution reads Microsoft release metadata and records archive URLs, SHA-512s, and bundled runtime in `MODULE.bazel.lock` (commit it). Later resolutions reuse lockfile facts (even after extension changes) and verify hashes; missing SDK/platform needs metadata access. No SDK allowlist or separate updater.

`global_json` supports case-insensitive `disable`, `patch` (default; prefers requested, else highest eligible patch in band), `latestPatch`, and `latestFeature` (highest band/patch in same major/minor), plus `allowPrerelease` (explicit preview implies prerelease). Uses published release metadata (not installed SDKs) locked in `sdk-policy-v1` facts (new metadata does not advance committed selections). Other policies and machine-local search paths fail.

After changing a pin: run `bazel run //:update_packages` (if package-backed), then `bazel run //:sync`, and commit `global.json`, package locks, `MODULE.bazel.lock`, and generated graph. Enforce locks in CI with `--lockfile_mode=error`. After switching Bazel versions, run once in update mode for registry entries (SDK facts survive; `--lockfile_mode=off` discards reuse; `refresh` keeps SDK facts). To refresh a roll-forward selection:

```sh
bazel run @dotnet//:update -- --nuget-update //:update_packages --sync //:sync
```

Updates the named root-module policy, keeping existing hashes and unrelated pins intact (declarations sharing a policy update together). Stops on failure (package failure leaves native locks/graph intact, though SDK selection may have advanced). Omit `--nuget-update` without packages, omit `--sync` to skip graph regen, or pass `--bazel /path/to/bazel` (else `RULES_MSBUILD_BAZEL` or `bazel`). Exact/disabled pins require editing their authored version.

`platforms` defaults to Linux/macOS ARM64/x64. Windows is opt-in with `platforms = ["win-x64"]` or `["win-arm64"]`; metadata resolution selects the verified ZIP archive and declares `dotnet.exe`. Native Windows execution has a separate bootstrap and isolation qualification gate; see [support limits](support.md). Optional `metadata_urls` sets `releases.json` mirrors (changing creates a separate resolution). See [qualified SDKs](support.md#qualified-sdks).

Private archives: `dotnet.sdk_archive(name, version, runtime_version, platform, urls, integrity, type = "")` + `register_toolchains("@name//:all")` (`integrity` mandatory; optional `type = "tar.zst"` supports zstd and suffixless URLs; archive must contain `dotnet` (`dotnet.exe` on Windows), SDK, and CoreCLR; platforms: Linux/macOS ARM64/x64 and opt-in Windows ARM64/x64). Adapters compile for the SDK's bundled framework and require C# 12, .NET 10, and MSBuild 18+ with stable `Microsoft.Build.ProjectCache` (SDK 8/9 engines unsupported; acquisition alone does not qualify old SDKs/workloads).

Hash-verified SDK repos are reproducible: `--repo_contents_cache` reuses expanded layouts across workspaces/bases, `--repository_cache` caches archives, and Bazel 9.3 adds `--experimental_remote_repo_contents_cache` (does not enable RBE; see [qualification](support.md#declared-native-preparation)).

`msbuild_sdk` wraps a downloaded or produced layout rooted beside its declared executable. Windows uses `dotnet.exe`, including runtime host entry points. Register `<name>_registered` and `<name>_runtime_registered`; a producer needs a separate bootstrap toolchain, and host-path SDK repos are unsupported. `runtime_host` selects a declared `msbuild_runtime` (`dotnet` or `corerun`) independently of compilation (newer hosts run older targets only when `runtimeconfig` allows).

## Runtimes

App/test execution uses the SDK's bundled shared frameworks (including ASP.NET) by default. To override the execution host with an exact CoreCLR (or ASP.NET via `kind = "aspnetcore"`, default `"coreclr"`, kept separate even for same version/metadata URL):

```starlark
dotnet.runtime(name = "app_runtime", version = "10.0.12")
use_repo(dotnet, "app_runtime")
```

Set `runtime_host = "@app_runtime//:runtime"` on the app/test target (compilation SDK unchanged; app `runtimeconfig` controls compatibility/roll-forward). For Windows CoreCLR or complete ASP.NET ZIPs, select `win-x64` or `win-arm64` in `platforms`. Uses the same metadata, hash verification, `MODULE.bazel.lock` facts, `platforms`, `metadata_urls`, and `--lockfile_mode=error` flow as `dotnet.sdk` (recoverable without metadata when archives are in repository cache or locked URLs).

Private layouts: `dotnet.runtime_archive(name, version, platform, urls, integrity)`. Source-built `msbuild_runtime` targets use the same `runtime_host` handoff; other shared frameworks need a complete declared layout.

For source-runtime builds: export a reference tree via `msbuild_graph_output`, bind it via `msbuild_sync.inputs`, compose shared-framework producers with `msbuild_runtime_layout` (or existing host layout with `msbuild_layout`), and pass the resulting `msbuild_runtime` as `runtime_host` (no manual products archive/hash report; exercised by [JIT qualification](support.md#unchanged-jit-tests)).

## Tests

`test_protocol`: `executable` (default; `expected_exit_code` 0–255, default 0, CoreCLR often 100), `mtp` (direct execution, no separate runner), or `vstest` (declared `test_runner`/`test_adapters` from locked packages; requires dotnet host). Implementation dep changes invalidate tests via their complete runtime layout even when the test DLL is unchanged.

Supports `data_paths`, `env`, `test_working_directory`, `test_output_dirs`, `test_settings`/`test_settings_output`, and `--test_filter` (MTP supports `test_filter_argument`). Empty selections fail unless `allow_empty_tests` is set. MTP/VSTest collect TRX and emit Bazel XML; failures, crashes, timeouts, and missing/malformed results fail. Sharding unsupported. See [test attributes](../msbuild/private/test_options.bzl).

Binaries and executable tests run their selected runtime directly (staging app + data in a private writable dir by default); MTP/VSTest use a managed adapter. For read-only executable smoke tests, `direct_executable_smoke = True` on `msbuild_graph_test` runs the DLL in place (args/exit pass through; must run from Bazel test working dir without a writable copy beside the DLL; requires `executable`, exit 0, dotnet host, and no custom host env, settings, adapters, data paths, custom test dirs, filtering, or sharding).

## Caching and workers

Bazel caches unchanged graph actions; changed graphs need a Linux persistent worker or HTTP project cache (fresh local actions start empty). Stable paths default on only on the declared qualified execution platform above (portable platforms use ordinary actions). Closed bundled `Microsoft.NET.Sdk` graphs without package tasks, custom documents, or dynamic Compile globs infer a conservative Restore contract keying all declared source bytes (`preparedRestore: false` disables globally or per project; custom Restore hooks/outputs need explicit contracts). Generated Restore actions fall back to ordinary Restore on portable platforms or with `linux_stable_paths = False`.

Snapshot replay defaults to filesystem clones with verified private-copy fallback (`RULES_MSBUILD_GRAPH_COPY_MODE=copy` forces copies for diagnosis; read before MSBuild evaluation).

On native Windows x64, `app_graph(name = "graph", windows_isolation = True)` selects AppContainer isolation for that graph build. Regenerate older wrappers with `bazel run //:sync` to expose the option. To isolate sync evaluation too, set `windows_isolation = True` on `msbuild_sync` and list the complete authored workspace in `srcs`. Bazel stages those files, declared bindings and the SDK in a private x64 AppContainer. A successful run publishes the two generated graph declarations. The Windows sync action uses fresh local qualification.

`linux_worker = None` (default on `msbuild_graph` and newly generated `app_graph`) enables workers only for `target = "Build"` with stable paths on the declared qualified Ubuntu ARM64 execution platform (target-platform marker alone does not enable it; Restore, Pack, Publish, and portable runs stay ordinary). `linux_worker = False` or `linux_stable_paths = False` opts out; explicit `linux_worker = True` works with stable paths including reviewed Publish. Bazel selects worker strategy automatically; `--worker_sandboxing` enables the outer worker sandbox. Older wrappers with explicit `linux_worker = False` keep that opt-out until resynced. See [worker qualification](support.md#linux-worker-qualification) and [limits](support.md#limits).

Retention budgets (not peak RSS caps): `worker_cache_mb` defaults to 4096 logical MiB; `evaluation_cache_mb` defaults to 512 MiB (`0` disables). Profiling is off by default. Reviewed `evaluationReuseInputs` (paths or `@(Compile)`, which with Compile globs also reviews future members) retain evaluation with prepared Restore and stable workers; other input/config/membership changes and failures reset it. Byte verification stays fresh; arbitrary evaluation-time external/process reads cannot be safely retained. Opt in per project via sync mappings after verifying contents cannot affect evaluation (property functions, custom evaluation-time reads):

```json
{"projects":{"App/App.csproj":{"preparedRestore":true,"evaluationReuseInputs":["Program.cs"]}}}
```

Enable both cache layers against a trusted HTTP AC/CAS service (optional `RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN`):

```sh
bazel build //:graph --remote_cache=http://cache:9090 \
  --action_env=RULES_MSBUILD_PROJECT_CACHE_URL=http://cache:9090 \
  --remote_download_outputs=all
```

Both caches have separate keys; Restore hits skip preparation; SDK/package acquisition is separate. Missing blobs rebuild; corruption fails; transfers retry/verify. Read-only independent consumer:

```sh
bazel build //:graph --remote_cache=http://cache:9090 \
  --remote_upload_local_results=false \
  --action_env=RULES_MSBUILD_PROJECT_CACHE_URL=http://cache:9090 \
  --action_env=RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1
```

`RULES_MSBUILD_PROJECT_CACHE_READ_ONLY` (`0` default, `1` read-only) fetches snapshots and builds misses locally without sending project-cache PUTs or repairing missing entries; applies to prepared sync qualification and cache seeding too (direct `ProjectSync` uses `--qualification-cache-read-only` with `--qualification-cache`). Source-runtime setup persists this mode (changing requires a fresh output).

Publication policy requires serialized publishing processes per shared endpoint/key namespace across all hosts/containers (a single host alone does not serialize processes; use separate read-only credentials where supported—the client flag is not access control). Concurrent identical writes keep complete content-addressed snapshots; serialized divergent outputs fail before replacing pointers. Ordinary Bazel HTTP AC lacks conditional-write atomicity, so racing divergent writers are unsupported (local locks or post-upload checks do not establish cross-machine atomicity). Failed uploads may leave unreferenced CAS blobs; action pointers publish only after all payloads and manifests complete.

Cache recovery is neither remote execution nor proof of filesystem hermeticity.
