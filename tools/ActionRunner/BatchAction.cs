namespace ActionRunner;

// Experimental whole-graph action. This output is not a project replay bundle.
internal static class BatchAction
{
    public static async Task RunAsync(ActionRequest request, Workspace workspace)
    {
        var project = request.GraphProject;
        if (project is null || !Files.ValidRelativePath(project) || !project.EndsWith(".csproj", StringComparison.Ordinal) ||
            request.Packages.Length != 0 || request.GraphDependencies is { Length: > 0 })
            throw new InvalidDataException("batch probe requires a package-free graph entry");
        var environment = new Dictionary<string, string>(BuildInvocation.Create(request, workspace, workspace.Output).Environment);
        var invocation = new BuildInvocation(workspace.Dotnet, workspace.Root,
            [.. BuildInvocation.EngineArguments(request, workspace.SdkRoot), project, "-t:Build",
                "-p:Configuration=Release", "-p:TargetFramework=net10.0", "-graphBuild", "-isolateProjects",
                "-m:2", "-nodeReuse:false", "-nologo", "-verbosity:normal"], environment);
        var result = await ProcessRunner.RunAsync(invocation.CreateStartInfo(), TimeSpan.FromSeconds(600), default);
        File.WriteAllText(Path.Combine(workspace.Diagnostics, "build.log"), result.Log);
        var compiles = result.Log.Split('\n').Count(line => line.Contains("/Roslyn/bincore/csc", StringComparison.Ordinal) && line.Contains(" /noconfig ", StringComparison.Ordinal));
        JsonFiles.Write(Path.Combine(workspace.Diagnostics, "action.json"), new { command = invocation.Arguments, returncode = result.ExitCode, compiles });
        if (result.ExitCode != 0 || result.TimedOut) throw new InvalidOperationException("batch MSBuild failed; see diagnostics/build.log");
        var folder = Path.Combine(workspace.Root, Path.GetDirectoryName(project)!, "bin/Release/net10.0");
        if (!Directory.Exists(folder)) throw new InvalidDataException("batch output missing");
        var manifest = new List<Artifact>();
        foreach (var source in Directory.EnumerateFiles(folder, "*", SearchOption.AllDirectories).Order(StringComparer.Ordinal))
        {
            var relative = Path.GetRelativePath(folder, source);
            Files.Copy(source, Path.Combine(workspace.Output, "app", relative));
            manifest.Add(new Artifact(relative, new FileInfo(source).Length, Files.Hash(source)));
        }
        JsonFiles.Write(Path.Combine(workspace.Output, "artifacts.json"), manifest);
        Directory.Delete(workspace.Scratch, recursive: true);
        JsonFiles.Write(Path.Combine(workspace.Output, "batch.json"), new { schemaVersion = 1, kind = "experimental-whole-graph", artifactsSha256 = Files.Hash(Path.Combine(workspace.Output, "artifacts.json")) });
        Files.NormalizeTree(workspace.Output);
    }
}
