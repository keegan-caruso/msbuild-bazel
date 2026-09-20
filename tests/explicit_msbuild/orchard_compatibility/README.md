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
