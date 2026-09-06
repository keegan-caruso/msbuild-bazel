namespace ActionRunner;

internal static class Msbuild
{
    public static async Task RunAsync(ActionRequest request, Workspace workspace, string bundle, string[] packages,
        CancellationToken cancellationToken = default)
    {
        var invocation = BuildInvocation.Create(request, workspace, bundle);
        var result = await ProcessRunner.RunAsync(invocation.CreateStartInfo(), TimeSpan.FromSeconds(180), cancellationToken);
        var evidence = BuildEvidence.Parse(result.Log);
        File.WriteAllText(Path.Combine(workspace.Diagnostics, "build.log"), result.Log);
        var report = new BuildReport(
            request.Project, workspace.Root, [invocation.Executable, .. invocation.Arguments], packages,
            evidence.PackageTargets, result.ExitCode, evidence.CompiledProjects, evidence.ReplayHits,
            Directory.EnumerateFiles(Path.Combine(workspace.Root, "Shared"), "*.cs")
                .Select(path => Path.GetRelativePath(workspace.Root, path)).Order(StringComparer.Ordinal).ToArray());
        JsonFiles.Write(Path.Combine(workspace.Diagnostics, "action.json"), report);
        Console.Write(result.Log);
        if (result.TimedOut) throw new TimeoutException("MSBuild exceeded 180 seconds");
        if (result.ExitCode != 0) throw new InvalidOperationException($"MSBuild {request.Project} failed with {result.ExitCode}");
        evidence.Verify(request.Project);
    }
}
