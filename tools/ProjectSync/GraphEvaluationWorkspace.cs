using System.Diagnostics;
using System.Xml.Linq;

namespace RulesMSBuild.ProjectSync;

// Package evaluation runs only in an owned copy, never through source symlinks.
internal sealed class GraphEvaluationWorkspace : IDisposable
{
    internal string Root { get; } = CreateRoot();
    private readonly QualificationRestoreCache? restoreCache;

    internal void SaveRestore() => restoreCache?.Save();

    private static string CreateRoot()
    {
        if (!QualificationSandbox.Inside)
        {
            return WorkspaceView.PhysicalPath(Directory.CreateTempSubdirectory("graph-sync-").FullName);
        }
        var path = QualificationSandbox.Base + "/scratch/evaluation";
        if (Directory.Exists(path))
        {
            throw new InvalidDataException("Qualification requires a fresh private evaluation workspace");
        }
        return Directory.CreateDirectory(path).FullName;
    }

    internal GraphEvaluationWorkspace(string source, string sdk, IEnumerable<string> entries,
        Dictionary<string, string> properties, WorkspaceView view, Dictionary<string, string>? toolProperties = null, Dictionary<string, Dictionary<string, string>>? entryProperties = null, QualificationOptions? cache = null, GraphMappings? mappings = null)
    {
        using var profile = SyncProfile.Measure("offline-preparation");
        try
        {
            using (SyncProfile.Measure("workspace-copy"))
            {
                Copy(source, Root);
            }
            // Bound artifacts remain inputs even when their logical path contains
            // bin/obj, which ordinary authored-source copying excludes.
            foreach (var path in view.ProducerRoots.Concat(view.Labels.Keys).Distinct(StringComparer.Ordinal))
            {
                var target = Path.Combine(Root, path);
                if (Directory.Exists(Path.Combine(source, path)))
                {
                    Directory.CreateDirectory(target);
                    continue;
                }
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                if (!File.Exists(target))
                {
                    File.Copy(Path.Combine(source, path), target);
                }
            }
            properties = new Dictionary<string, string>(properties, StringComparer.OrdinalIgnoreCase) { ["NetCoreSdkRoot"] = sdk };
            var sdkRoot = Path.GetDirectoryName(Path.GetDirectoryName(sdk))!;
            foreach (var (name, path) in toolProperties ?? [])
            {
                GraphGenerator.ValidateToolProperty(name, properties);
                properties.Add(name, Path.Combine(Root, path));
            }
            restoreCache = cache is null ? null : new QualificationRestoreCache(Root, sdkRoot, entries, properties, view, mappings!, cache);
            var feed = Path.Combine(Root, ".package-source");
            Directory.CreateDirectory(feed);
            foreach (var archive in view.GraphPackageArchives())
            {
                File.Copy(archive, Path.Combine(feed, Path.GetFileName(archive)));
            }
            var config = Path.Combine(Root, ".graph.nuget.config");
            File.WriteAllText(config, "<configuration><packageSources><clear/></packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>");
            if (restoreCache?.Restore() == true)
            {
                return;
            }
            using var packageSdks = RulesMSBuild.PackageSdks.Prepare(Root);
            var roots = entries.ToArray();
            var coordinator = Root + ".restore.proj";
            try
            {
                // Keep each authored Restore target and its global properties, but
                // let one MSBuild invocation reuse shared dependency evaluations.
                if (roots.Length > 1)
                {
                    using var file = File.Create(coordinator);
                    var requests = roots.Select(entry => new XElement("MSBuild",
                        new XAttribute("Projects", Microsoft.Build.Evaluation.ProjectCollection.Escape(Path.Combine(Root, WorkspaceView.Safe(entry)))),
                        new XAttribute("Targets", "Restore"),
                        new XAttribute("BuildInParallel", "false"),
                        new XAttribute("Properties", string.Join(';', RestoreProperties(entry)
                            .Select(property => GraphEntryProperties.Assignment(property.Key, property.Value))))));
                    new XDocument(new XElement("Project", new XElement("Target", new XAttribute("Name", "Restore"), requests))).Save(file);
                }
                var start = new ProcessStartInfo(Path.Combine(sdkRoot, "dotnet")) { WorkingDirectory = Root };
                foreach (var argument in new[] { "restore", roots.Length > 1 ? coordinator : Path.Combine(Root, WorkspaceView.Safe(roots[0])), "--configfile", config,
                    "--source", feed, "--packages", Path.Combine(Root, ".nuget"), "-p:NuGetAudit=false",
                    "-p:RestoreFallbackFolders=", "-p:RestoreAdditionalProjectSources=", "-p:RestoreAdditionalProjectFallbackFolders=" })
                {
                    start.ArgumentList.Add(argument);
                }
                if (roots.Length == 1)
                {
                    foreach (var (key, value) in RestoreProperties(roots[0]))
                    {
                        start.ArgumentList.Add(GraphEntryProperties.Argument(key, value));
                    }
                }
                start.Environment["DOTNET_ROOT"] = sdkRoot;
                start.Environment["DOTNET_CLI_HOME"] = Path.Combine(Root, ".cli");
                start.Environment["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1";
                start.Environment["DOTNET_GENERATE_ASPNET_CERTIFICATE"] = "false";
                start.Environment["MSBUILDDISABLENODEREUSE"] = "1";
                using var restoreProfile = SyncProfile.Measure("offline-restore");
                using var process = Process.Start(start)!;
                process.WaitForExit();
                if (process.ExitCode != 0)
                {
                    throw new InvalidDataException("Graph sync offline Restore failed for " + string.Join(", ", roots) + "; check the declared package closure");
                }
            }
            finally
            {
                File.Delete(coordinator);
            }

            packageSdks?.Dispose();
            restoreCache?.Capture();

            Dictionary<string, string> RestoreProperties(string entry)
            {
                // Restore all authored frameworks, even when Build selects one.
                var selected = GraphEntryProperties.For(entry, properties, entryProperties ?? []);
                selected.Remove("TargetFramework");
                if (File.Exists(NuGetLocks.ForProject(Path.Combine(Root, entry))) ||
                    GraphSolutions.IsSolution(entry) && Directory.EnumerateFiles(Root, "*.lock.json", SearchOption.AllDirectories).Any(NuGetLocks.IsLockFile))
                {
                    selected["RestoreLockedMode"] = "true";
                }
                return selected;
            }
        }
        catch
        {
            Dispose();
            throw;
        }
    }

    private static void Copy(string source, string destination, bool top = true)
    {
        foreach (var path in Directory.EnumerateFileSystemEntries(source))
        {
            var name = Path.GetFileName(path);
            if (top && name is ("graph.generated.json" or "graph.generated.bzl") || name is ".git" or ".tools" or ".cache" or ".nuget" or ".package-source" or ".cli" or "bin" or "obj" || name.StartsWith("bazel-", StringComparison.Ordinal) && Directory.Exists(path))
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
                Copy(path, target, false);
            }
            else
            {
                File.Copy(path, target, false);
            }
        }
    }

    public void Dispose()
    {
        restoreCache?.Dispose();
        Directory.Delete(Root, true);
    }
}
