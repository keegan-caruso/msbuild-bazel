using System.Diagnostics;

namespace RulesMSBuild.ProjectSync;

// Package evaluation runs only in an owned copy, never through source symlinks.
internal sealed class GraphEvaluationWorkspace : IDisposable
{
    internal string Root { get; } = WorkspaceView.PhysicalPath(Directory.CreateTempSubdirectory("graph-sync-").FullName);

    internal GraphEvaluationWorkspace(string source, string sdk, string sdkDirectory, IEnumerable<string> entries,
        Dictionary<string, string> properties, WorkspaceView view, Dictionary<string, string>? toolProperties = null, Dictionary<string, Dictionary<string, string>>? entryProperties = null)
    {
        try
        {
            Copy(source, Root);
            properties = new Dictionary<string, string>(properties, StringComparer.OrdinalIgnoreCase);
            foreach (var (name, path) in toolProperties ?? [])
            {
                GraphGenerator.ValidateToolProperty(name, properties);
                properties.Add(name, Path.Combine(Root, path));
            }
            var feed = Path.Combine(Root, ".package-source");
            Directory.CreateDirectory(feed);
            foreach (var archive in view.GraphPackageArchives())
            {
                File.Copy(archive, Path.Combine(feed, Path.GetFileName(archive)));
            }
            using var packageSdks = RulesMSBuild.PackageSdks.Prepare(Root);
            var config = Path.Combine(Root, ".graph.nuget.config");
            File.WriteAllText(config, "<configuration><packageSources><clear/></packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>");
            foreach (var entry in entries)
            {
                var start = new ProcessStartInfo(Path.Combine(sdk, "dotnet")) { WorkingDirectory = Root };
                foreach (var argument in new[] { "restore", Path.Combine(Root, WorkspaceView.Safe(entry)), "--configfile", config,
                    "--source", feed, "--packages", Path.Combine(Root, ".nuget"), "-p:NuGetAudit=false",
                    "-p:NetCoreSdkRoot=" + sdkDirectory, "-p:RestoreFallbackFolders=", "-p:RestoreAdditionalProjectSources=", "-p:RestoreAdditionalProjectFallbackFolders=" })
                {
                    start.ArgumentList.Add(argument);
                }
                // Restore each project's authored frameworks; the build graph still selects its requested framework.
                foreach (var (key, value) in GraphEntryProperties.For(entry, properties, entryProperties ?? []).Where(property => !property.Key.Equals("TargetFramework", StringComparison.OrdinalIgnoreCase)))
                {
                    start.ArgumentList.Add("-p:" + key + "=" + value);
                }
                start.Environment["DOTNET_ROOT"] = sdk;
                start.Environment["DOTNET_CLI_HOME"] = Path.Combine(Root, ".cli");
                start.Environment["MSBUILDDISABLENODEREUSE"] = "1";
                using var process = Process.Start(start)!;
                process.WaitForExit();
                if (process.ExitCode != 0)
                {
                    throw new InvalidDataException("Graph sync offline Restore failed for " + entry + "; check the declared package closure");
                }
            }
        }
        catch
        {
            Dispose();
            throw;
        }
    }

    private static void Copy(string source, string destination)
    {
        foreach (var path in Directory.EnumerateFileSystemEntries(source))
        {
            var name = Path.GetFileName(path);
            if (name is ".git" or ".tools" or ".cache" or ".nuget" or ".package-source" or ".cli" or "bin" or "obj" || name.StartsWith("bazel-", StringComparison.Ordinal))
            {
                continue;
            }
            var target = Path.Combine(destination, name);
            if (Directory.Exists(path))
            {
                if (new DirectoryInfo(path).LinkTarget is not null)
                {
                    throw new InvalidDataException("Graph sync directory symlink requires an explicit input: " + path);
                }
                Directory.CreateDirectory(target);
                Copy(path, target);
            }
            else
            {
                File.Copy(path, target);
            }
        }
    }

    public void Dispose() => Directory.Delete(Root, true);
}
