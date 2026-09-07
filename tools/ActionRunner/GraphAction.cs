using System.Text.Json;
using System.Text.Json.Nodes;

namespace ActionRunner;

// Graph execution is additive: the original two-project controls retain their request contract.
internal static class GraphAction
{
    public static async Task RunAsync(ActionRequest request, Workspace workspace)
    {
        var project = request.GraphProject!;
        if (!Files.ValidRelativePath(project) || !project.EndsWith(".csproj", StringComparison.Ordinal))
            throw new InvalidDataException("graph project path invalid");
        var properties = request.GraphGlobalProperties ?? new Dictionary<string, string> { ["configuration"] = "Release" };
        if (!properties.TryGetValue("configuration", out var configuration) || configuration != "Release" ||
            properties.Any(pair => pair.Key != "configuration" && pair.Key != "flavor" && (pair.Key != "targetframework" || pair.Value != "net10.0")))
            throw new InvalidDataException("unsupported graph execution configuration");
        if (properties.Any(pair => pair.Value.Contains(';') || pair.Value.Contains(',') || pair.Value.Contains('\n')))
            throw new InvalidDataException("unsupported graph property value");
        if (request.GraphAssetsFile is not null && !Files.ValidRelativePath(request.GraphAssetsFile))
            throw new InvalidDataException("graph assets path invalid");
        var packages = PackageInputs.Stage(request, workspace.Root);
        var dependencies = new List<string>();
        var dependencyProjects = new List<string>();
        var stagedPaths = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var input in request.GraphDependencies ?? [])
        {
            var sealPath = Path.Combine(input, "bundle.json");
            if (!File.Exists(sealPath)) throw new InvalidDataException("dependency bundle incomplete");
            var seal = JsonNode.Parse(File.ReadAllText(sealPath))!;
            if (seal["schemaVersion"]?.GetValue<int>() != 1 ||
                seal["resultsSha256"]?.GetValue<string>() != Files.Hash(Path.Combine(input, "results.json")) ||
                seal["artifactsSha256"]?.GetValue<string>() != Files.Hash(Path.Combine(input, "artifacts.json")))
                throw new InvalidDataException("dependency bundle metadata corrupt");
            var payload = JsonNode.Parse(File.ReadAllText(Path.Combine(input, "results.json")))!;
            var dependencyProject = payload["project"]!.GetValue<string>();
            if (!Files.ValidRelativePath(dependencyProject))
                throw new InvalidDataException("invalid dependency project");
            dependencies.Add(Path.GetFullPath(input));
            dependencyProjects.Add(dependencyProject);
            var directory = Path.GetDirectoryName(dependencyProject)!;
            var prefix = string.IsNullOrEmpty(directory) ? "" : directory + "/";
            var artifacts = JsonFiles.Read<Artifact[]>(Path.Combine(input, "artifacts.json"));
            if (artifacts.Length == 0) throw new InvalidDataException("dependency artifacts empty");
            foreach (var artifact in artifacts)
            {
                if (!Files.ValidRelativePath(artifact.Path) ||
                    !(artifact.Path.StartsWith(prefix + "bin/", StringComparison.Ordinal) ||
                      artifact.Path.StartsWith(prefix + "obj/", StringComparison.Ordinal)))
                    throw new InvalidDataException("dependency artifact path invalid");
                var source = Path.Combine(input, "artifacts", artifact.Path);
                Files.Verify(source, artifact.Size, artifact.Sha256, "dependency artifact missing or corrupt");
                if (stagedPaths.TryGetValue(artifact.Path, out var prior) && prior != artifact.Sha256)
                    throw new InvalidDataException("configured dependency artifact collision");
                stagedPaths[artifact.Path] = artifact.Sha256;
                Files.Copy(source, Path.Combine(workspace.Root, artifact.Path));
            }
        }
        const string targets = "GetTargetFrameworks;Build;GetNativeManifest;GetCopyToOutputDirectoryItems;GetTargetFrameworksWithPlatformForSingleTargetFramework;GetCopyToPublishDirectoryItems";
        var environment = new Dictionary<string, string>(BuildInvocation.Create(request, workspace, workspace.Output).Environment)
        {
            ["RULES_MSBUILD_REPLAY_MODE"] = "capture",
            ["RULES_MSBUILD_GRAPH_PROJECT"] = project,
            ["RULES_MSBUILD_GRAPH_PROPERTIES"] = JsonSerializer.Serialize(properties),
            ["RULES_MSBUILD_GRAPH_DEPENDENCIES"] = JsonSerializer.Serialize(dependencies)
        };
        if (SelectedFrameworks.Stage(request, workspace) is { } selectionTargets)
            environment["RULES_MSBUILD_GRAPH_SELECTION_TARGETS"] = selectionTargets;
        var invocation = new BuildInvocation(workspace.Dotnet, workspace.Root,
            ["msbuild", project, "-t:" + targets, .. properties.OrderBy(pair => pair.Key, StringComparer.Ordinal).Select(pair => "-p:" + pair.Key + "=" + pair.Value), "-graphBuild", "-isolateProjects", "-nodeReuse:false", "-nologo", "-verbosity:normal"], environment);
        var result = await ProcessRunner.RunAsync(invocation.CreateStartInfo(), TimeSpan.FromSeconds(180), default);
        File.WriteAllText(Path.Combine(workspace.Diagnostics, "build.log"), result.Log);
        var evidence = BuildEvidence.Parse(result.Log);
        JsonFiles.Write(Path.Combine(workspace.Diagnostics, "action.json"), new {
            project, workspace = workspace.Root, command = invocation.Arguments, returncode = result.ExitCode,
            compiledProjects = evidence.CompiledProjects.Select(Path.GetFileNameWithoutExtension).ToArray(), replayHits = evidence.ReplayHits, packages
        });
        Console.Write(result.Log);
        if (result.ExitCode != 0 || result.TimedOut) throw new InvalidOperationException("graph MSBuild failed");
        if (!evidence.CompiledProjects.SequenceEqual([project]))
            throw new InvalidOperationException("unexpected graph project compilation");
        if (!evidence.ReplayHits.Order().SequenceEqual(dependencyProjects.Select(Path.GetFileNameWithoutExtension).Order()))
            throw new InvalidOperationException("incomplete graph dependency replay");
        var manifest = new List<Artifact>();
        var projectDirectory = Path.GetDirectoryName(project)!;
        var projectPrefix = projectDirectory.Length == 0 ? "" : projectDirectory + "/";
        foreach (var directory in request.GraphOutputDirectories ?? [Path.Combine(projectDirectory, "bin/Release/net10.0"), Path.Combine(projectDirectory, "obj/Release/net10.0/ref")])
        {
            if (!Files.ValidRelativePath(directory) || !(directory.StartsWith(projectPrefix + "bin/", StringComparison.Ordinal) || directory.StartsWith(projectPrefix + "obj/", StringComparison.Ordinal)))
                throw new InvalidDataException("graph output path invalid");
            var folder = Path.Combine(workspace.Root, directory);
            if (!Directory.Exists(folder)) continue;
            foreach (var source in Directory.EnumerateFiles(folder, "*", SearchOption.AllDirectories).Order(StringComparer.Ordinal))
            {
                var relative = Path.GetRelativePath(workspace.Root, source);
                Files.Copy(source, Path.Combine(workspace.Output, "artifacts", relative));
                manifest.Add(new Artifact(relative, new FileInfo(source).Length, Files.Hash(source)));
            }
        }
        if (manifest.Count == 0) throw new InvalidDataException("graph action produced no artifacts");
        JsonFiles.Write(Path.Combine(workspace.Output, "artifacts.json"), manifest);
        Bundles.CanonicalizeResults(Path.Combine(workspace.Output, "results.json"));
        foreach (var path in Directory.EnumerateFiles(workspace.Output, "graph-*.json"))
            File.Move(path, Path.Combine(workspace.Diagnostics, Path.GetFileName(path)));
        Directory.Delete(workspace.Scratch, recursive: true);
        Files.NormalizeTree(workspace.Output);
        // Commit marker is written only after every consumer-visible file is complete.
        var exportSealPath = Path.Combine(workspace.Diagnostics, "bundle-seal.json");
        JsonFiles.Write(exportSealPath, new {
            schemaVersion = 1,
            resultsSha256 = Files.Hash(Path.Combine(workspace.Output, "results.json")),
            artifactsSha256 = Files.Hash(Path.Combine(workspace.Output, "artifacts.json"))
        });
        if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(exportSealPath,
            UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.GroupRead | UnixFileMode.OtherRead);
        File.SetLastWriteTimeUtc(exportSealPath, DateTime.UnixEpoch);
        File.Move(exportSealPath, Path.Combine(workspace.Output, "bundle.json"));
        Directory.SetLastWriteTimeUtc(workspace.Output, DateTime.UnixEpoch);
    }
}
