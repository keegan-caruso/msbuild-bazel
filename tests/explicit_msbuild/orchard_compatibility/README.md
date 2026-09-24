# Pinned Orchard compatibility probe

This is disposable Linux test scaffolding, not a production BUILD generator.
Use Orchard commit `04467a3438d4255627c1a478598a1585b3ff2947` and SDK 10.0.400/Bazel
8.4.2 in the pinned Ubuntu ARM64 image. Copy the rules repo to `/workspace`, the
clean Orchard checkout (without `.git`, `bin`, `obj`, or `node_modules`) to
`/orchard-work`, and make `/evidence` writable. All builds use native Linux storage.
Set `RULES_MSBUILD_DOTNET_ROOT` and `RULES_MSBUILD_BAZEL` to the pinned tools.

1. Copy `GraphProbe.cs.txt` to `/probe/Program.cs` and `GraphProbe.csproj.txt` to
   `/probe/Probe.csproj`. Run:

   ```sh
   dotnet run --project /probe/Probe.csproj -- /orchard-work \
     src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj /evidence/evaluated.json
   ```

2. Expose cached nupkg archives as a flat feed at `/tmp/feed`, restore packages to
   `/tmp/nuget`, and build the raw leaf control from `/orchard-work`:

   ```sh
   dotnet build src/OrchardCore/OrchardCore.ContentPreview.Abstractions/OrchardCore.ContentPreview.Abstractions.csproj \
     -c Release -p:RestoreSources=/tmp/feed -p:RestorePackagesPath=/tmp/nuget -p:NuGetAudit=false
   ```

   This creates the generator's assets file and extracts its locked packages.
   Package acquisition is setup outside Bazel actions. The test uses those exact
   assets/archive content hashes; the necessary cache must be provisioned first.

3. Build `/workspace/tools/ExplicitBuild` using `scripts/dotnet.sh`, provide a
   preseeded Bazel repository cache at `/tmp/repository-cache`, and run
   `python3 bazel_probe.py`. The script writes BUILD/MODULE files only into the
   disposable Orchard copy, runs four expected-failure probes, writes their logs
   and `/evidence/bazel-report.json`, and shuts down its Bazel server.

4. Raw full-application control:

   ```sh
   dotnet build src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj -c Release \
     -p:RestoreSources=/tmp/feed -p:RestorePackagesPath=/tmp/nuget -p:NuGetAudit=false -m:4
   ```

   For the startup smoke, run its `bin/Release/net10.0/OrchardCore.Cms.Web.dll` from
   the web project directory with `--urls http://127.0.0.1:5087`, check HTTP GET `/`,
   and terminate the server. Do not submit tenant setup as part of this probe.

The graph scanner selects the first declared framework per project; this pinned
closure has one each. It inventories evaluated project edges before restore, not
all dynamic MSBuild target calls. Preserve runtime/Razor qualification as separate
work after the confirmed blockers are fixed.

The probe now expects the private/central package cases to succeed, using declared
`.editorconfig` and analyzer AdditionalFiles inputs. Historical failure evidence
in the [historical evidence directory](https://github.com/keegan-caruso/msbuild-bazel/tree/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/evidence/orchard-explicit-compatibility) describes the pre-fix baseline.

## Full graph benchmark

Use `FullGraphProbe.cs.txt` instead of the smaller inventory probe and write
`/evidence/full-evaluated.json` **before** building the raw source copy. Perform the
full application restore/build above, then run:

```sh
python3 /workspace/tests/explicit_msbuild/orchard_compatibility/full_graph.py \
  /orchard-work /evidence/full-evaluated.json /workspace
python3 /workspace/tests/explicit_msbuild/orchard_compatibility/benchmark.py \
  /orchard-work /evidence baseline --raw
```

The generated graph has one explicit target per project. Per-project package locks
are taken from the setup restore, with canonical extraction targets shared across
projects. Different framework-dependent dependency closures use
`msbuild_nuget_dependencies`; they do not duplicate archive extraction. Normal
project edges inherit framework references. Module name exports, resource metadata,
empty directories, analyzers and SDK imports remain explicit inputs. There are no
Orchard-specific production rule attributes.

Cold means deleted build outputs and restarted workers/Bazel, with already available
archives, SDK, repository cache and warm filesystem caches. Downloads, inventory,
BUILD generation and cleanup are outside timing. The command includes Bazel startup
and analysis. It uses four CPU slots and defaults to two isolated compiler workers
(`ORCHARD_WORKERS` overrides this); four compiler servers can exceed an 8 GiB VM's
usable memory on this graph. Raw MSBuild uses `-m:4`. Servers from the other build
mode are shut down before timing.

The body-edit case changes `NotFoundManifestInfo.Description` and asserts that the
reference assembly does not change. It restores the original source in `finally`.
All benchmark source/build state stays in the disposable Linux copy. Keep startup,
embedded resources, Razor behavior, and cache recovery as explicit acceptance checks
rather than treating successful compilation as sufficient runtime evidence.

After the local matrix, `smoke.py /orchard-work /evidence bazel-runtime` checks
setup-page rendering and three embedded assets. Add `--raw` to run the raw output
and compare asset hashes. `remote.py /orchard-work /evidence` seeds an HTTP cache,
then recovers all outputs at `/orchard-relocated` in a fresh output base. Its
loopback server is test scaffolding, not a production cache recommendation.
The producer output base is deleted before recovery. On a space-constrained host,
`--pause-before-recovery` writes `/evidence/remote-ready-for-recovery`; reclaim
unused container blocks, then create `/evidence/remote-continue` within five minutes.
Start with fresh disposable paths for an independent reproduction. `resource_edit.py` compares an embedded setup-CSS
edit with raw MSBuild and records whether the module reference assembly changed.

For a Bazel-only version comparison, add `--skip-raw` to `resource_edit.py`.
Use identical rules/SDK/input declarations and select each binary through
`RULES_MSBUILD_BAZEL`; use separate evidence directories for each run.

For fresh-execution reproducibility, run `reproducibility.py SOURCE EVIDENCE BASE`
in the qualified worker container after `full_graph.py`. Use a nonexistent output
base and a new evidence directory for each pass. It disables local/remote action
caches, requires 202 worker actions, and hashes all published reference/runtime
files. Delete producer state and relocate the source before a second pass; compare
`hashes.json` dictionaries. Diagnostic logs and worker timing/PID metadata are
intentionally excluded from byte comparisons.
