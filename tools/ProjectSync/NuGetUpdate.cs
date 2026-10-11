using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;

namespace RulesMSBuild.ProjectSync;

// NuGet resolves in an owned workspace. Builds consume only the resulting locks.
internal static class NuGetUpdate
{
    internal static async Task Run(string[] args)
    {
        if (args.Length < 3)
        {
            throw new ArgumentException("nuget-update <workspace> <sdk-root> <project>... [--output nuget.lock.json] [--configuration Release] [--check]");
        }
        var source = WorkspaceView.PhysicalPath(args[0]);
        var sdk = WorkspaceView.PhysicalPath(args[1]);
        var projects = new List<string>();
        var output = "nuget.lock.json";
        var configuration = "Release";
        string? sdkVersion = null;
        string? mappingPath = null;
        var framework = "";
        var check = false;
        for (var i = 2; i < args.Length; i++)
        {
            if (args[i] == "--check")
            {
                check = true;
            }
            else if (args[i] is "--output" or "--configuration" or "--sdk-version" or "--mappings" or "--framework")
            {
                var option = args[i];
                if (++i == args.Length)
                {
                    throw new ArgumentException(option + " requires a value");
                }
                if (option == "--output")
                {
                    output = WorkspaceView.Safe(args[i]);
                }
                else if (option == "--sdk-version")
                {
                    sdkVersion = WorkspaceView.Safe(args[i]);
                }
                else if (option == "--mappings")
                {
                    mappingPath = args[i];
                }
                else if (option == "--framework")
                {
                    framework = args[i];
                }
                else
                {
                    configuration = args[i];
                }
            }
            else if (args[i].StartsWith("--", StringComparison.Ordinal))
            {
                throw new ArgumentException("Unknown NuGet update option: " + args[i]);
            }
            else
            {
                projects.Add(WorkspaceView.Safe(args[i]));
            }
        }
        if (projects.Count == 0 || configuration.Length == 0 || new[] { configuration, framework }.Any(value => value.Any(c => !char.IsAsciiLetterOrDigit(c) && c is not '.' and not '_' and not '-')))
        {
            throw new ArgumentException("NuGet update requires entry projects and a simple configuration name");
        }
        var version = sdkVersion ?? Directory.GetDirectories(Path.Combine(sdk, "sdk")).Select(Path.GetFileName).Single();
        var engine = Path.Combine(sdk, "sdk", version!);
        if (!Directory.Exists(engine))
        {
            throw new InvalidDataException("Selected SDK version is missing: " + version);
        }
        System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (context, name) => File.Exists(Path.Combine(engine, name.Name + ".dll"))
            ? context.LoadFromAssemblyPath(Path.Combine(engine, name.Name + ".dll")) : null;
        var mappings = new GraphMappings(mappingPath is null ? null : Path.GetFullPath(mappingPath, source));
        var properties = new Dictionary<string, string>(mappings.Properties, StringComparer.OrdinalIgnoreCase) { ["Configuration"] = configuration };
        if (framework.Length != 0)
        {
            properties["TargetFramework"] = framework;
        }
        GraphEntryProperties.Validate(projects, mappings.EntryProperties, []);
        GraphSolutions.Validate(source, projects, properties.Keys.Concat(mappings.EntryProperties.Values.SelectMany(values => values.Keys)));
        // Resolution must not override the updater's feeds, isolation or lock policy.
        GraphEntryProperties.Validate(projects, projects.Distinct().ToDictionary(entry => entry, _ => properties
            .Where(pair => !pair.Key.Equals("RestoreUseStaticGraphEvaluation", StringComparison.OrdinalIgnoreCase))
            .ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.OrdinalIgnoreCase)), []);
        var destination = Path.Combine(source, output);
        if (File.Exists(destination))
        {
            using var existing = JsonDocument.Parse(File.ReadAllText(destination));
            if (existing.RootElement.GetProperty("generatedBy").GetString() != "RulesMSBuild.NuGetUpdate")
            {
                throw new InvalidDataException("Refusing to overwrite an authored NuGet manifest");
            }
        }
        var scratch = WorkspaceView.PhysicalPath(Directory.CreateTempSubdirectory("nuget-update-").FullName);
        try
        {
            var workspace = Path.Combine(scratch, "workspace");
            Directory.CreateDirectory(workspace);
            var originals = new Dictionary<string, string>(StringComparer.Ordinal);
            Copy(source, workspace, originals);
            NuGetConfigs.RequireRoot(workspace);
            var packageRoot = Path.Combine(scratch, "packages");
            var locks = new SortedDictionary<string, string>(StringComparer.Ordinal);
            foreach (var project in projects.Distinct())
            {
                await Restore(sdk, workspace, packageRoot, project, GraphEntryProperties.For(project, properties, mappings.EntryProperties), scratch);
                CaptureLocks(workspace, locks);
                NuGetConfigs.Capture(workspace, source, Path.Combine(scratch, "home"), originals);
            }
            Environment.SetEnvironmentVariable("HOME", Path.Combine(scratch, "home"));
            Environment.SetEnvironmentVariable("DOTNET_CLI_HOME", Path.Combine(scratch, "home"));
            Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(engine, "MSBuild.dll"));
            Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(engine, "Sdks"));
            Environment.SetEnvironmentVariable("DOTNET_HOST_PATH", Path.Combine(sdk, "dotnet"));
            Environment.SetEnvironmentVariable("NUGET_PACKAGES", packageRoot);
            Environment.SetEnvironmentVariable("NUGET_HTTP_CACHE_PATH", Path.Combine(scratch, "http"));
            Environment.SetEnvironmentVariable("MSBuildEnableWorkloadResolver", "false");
            string[] required;
            try
            {
                required = NuGetGraph.Projects(workspace, projects.Distinct(), properties, mappings.EntryProperties);
            }
            catch (Exception error)
            {
                throw new InvalidDataException("NuGet graph evaluation failed; existing locks were left unchanged: " + error.Message, error);
            }
            var restored = new HashSet<string>(StringComparer.Ordinal);
            foreach (var assets in Directory.GetFiles(workspace, "project.assets.json", SearchOption.AllDirectories))
            {
                using var document = JsonDocument.Parse(File.ReadAllText(assets));
                var project = document.RootElement.GetProperty("project").GetProperty("restore").GetProperty("projectPath").GetString()!;
                var relative = WorkspaceView.Safe(Path.GetRelativePath(workspace, project).Replace('\\', '/'));
                restored.Add(relative);
            }
            if (locks.Count == 0)
            {
                throw new InvalidDataException("Restore produced no project lockfiles");
            }
            if (required.Any(project => !restored.Contains(project)))
            {
                throw new InvalidDataException("NuGet Restore skipped graph projects; existing locks were left unchanged: " +
                    string.Join(", ", required.Where(project => !restored.Contains(project))));
            }
            var packages = await NuGetArchives.Read(packageRoot);
            var manifest = JsonSerializer.Serialize(new
            {
                generatedBy = "RulesMSBuild.NuGetUpdate",
                version = 1,
                sdkVersion = version,
                projects = projects.Distinct().Order(StringComparer.Ordinal).ToArray(),
                configuration,
                // Record authored configuration intent, including the build-only framework.
                properties,
                entryProperties = mappings.EntryProperties,
                configDigests = NuGetConfigs.Capture(workspace, source, Path.Combine(scratch, "home"), originals),
                lockFiles = locks.Keys.ToArray(),
                packages,
            }, new JsonSerializerOptions { WriteIndented = true }) + "\n";
            foreach (var (path, digest) in originals)
            {
                if (!File.Exists(path) || Digest(path) != digest)
                {
                    throw new InvalidDataException("Input changed during NuGet update: " + Path.GetRelativePath(source, path));
                }
            }
            var products = locks.ToDictionary(pair => Path.Combine(source, pair.Key), pair => pair.Value, StringComparer.Ordinal);
            if (!products.TryAdd(destination, manifest))
            {
                throw new InvalidDataException("NuGet manifest overlaps a project lockfile");
            }
            if (check)
            {
                if (products.Any(pair => !File.Exists(pair.Key) || File.ReadAllText(pair.Key) != pair.Value))
                {
                    throw new InvalidDataException("NuGet locks are stale; run the update target");
                }
            }
            else
            {
                Publish(products);
            }
            Console.WriteLine($"NuGet locks: {packages.Length} archives, {locks.Count} projects; {(check ? "current" : "updated")}");
        }
        finally
        {
            Directory.Delete(scratch, true);
        }
    }

    private static async Task Restore(string sdk, string workspace, string packages, string project, Dictionary<string, string> properties, string scratch)
    {
        if (!File.Exists(Path.Combine(workspace, project)))
        {
            throw new InvalidDataException("Missing entry project: " + project);
        }
        var start = new ProcessStartInfo(Path.Combine(sdk, "dotnet")) { WorkingDirectory = workspace, UseShellExecute = false };
        foreach (var argument in new[] { "restore", project, "--packages", packages, "--force-evaluate",
            "-p:RestorePackagesWithLockFile=true", "-p:RestoreLockedMode=false", "-p:NuGetAudit=false",
            "-p:RestoreFallbackFolders=", "-p:RestoreAdditionalProjectFallbackFolders=" })
        {
            start.ArgumentList.Add(argument);
        }
        foreach (var (name, value) in properties.Where(pair => !pair.Key.Equals("TargetFramework", StringComparison.OrdinalIgnoreCase)))
        {
            start.ArgumentList.Add(GraphEntryProperties.Argument(name, value));
        }
        foreach (var (name, value) in new Dictionary<string, string>
        {
            ["DOTNET_ROOT"] = sdk,
            ["DOTNET_NOLOGO"] = "1",
            ["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1",
            ["DOTNET_CLI_HOME"] = Path.Combine(scratch, "home"),
            ["HOME"] = Path.Combine(scratch, "home"),
            ["NUGET_PACKAGES"] = packages,
            ["NUGET_HTTP_CACHE_PATH"] = Path.Combine(scratch, "http"),
            ["NUGET_PLUGINS_CACHE_PATH"] = Path.Combine(scratch, "plugins"),
            ["DOTNET_MULTILEVEL_LOOKUP"] = "0",
            ["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1",
            ["DOTNET_GENERATE_ASPNET_CERTIFICATE"] = "false",
            ["MSBUILDDISABLENODEREUSE"] = "1"
        })
        {
            start.Environment[name] = value;
        }
        using var child = Process.Start(start) ?? throw new InvalidOperationException("Could not start NuGet Restore");
        await child.WaitForExitAsync();
        if (child.ExitCode != 0)
        {
            throw new InvalidDataException("NuGet Restore failed; existing locks were left unchanged");
        }
    }

    private static void CaptureLocks(string workspace, SortedDictionary<string, string> locks)
    {
        foreach (var assets in Directory.GetFiles(workspace, "project.assets.json", SearchOption.AllDirectories))
        {
            using var document = JsonDocument.Parse(File.ReadAllText(assets));
            var project = document.RootElement.GetProperty("project").GetProperty("restore").GetProperty("projectPath").GetString()!;
            var native = Path.Combine(Path.GetDirectoryName(project)!, "packages.lock.json");
            if (!File.Exists(native))
            {
                throw new InvalidDataException("Missing standard packages.lock.json for " + project + "; custom NuGetLockFilePath is unsupported");
            }
            var relative = WorkspaceView.Safe(Path.GetRelativePath(workspace, native).Replace('\\', '/'));
            var content = File.ReadAllText(native);
            if (locks.TryGetValue(relative, out var previous) && previous != content)
            {
                throw new InvalidDataException("Conflicting configured NuGet locks for " + relative + "; use separate workspaces; existing locks were left unchanged");
            }
            locks[relative] = content;
        }
    }

    private static string Digest(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream));
    }

    private static void Copy(string source, string destination, Dictionary<string, string> originals)
    {
        foreach (var path in Directory.EnumerateFileSystemEntries(source))
        {
            var name = Path.GetFileName(path);
            if (name is ".git" or ".tools" or ".cache" or ".nuget" or ".package-source" or ".cli" or "bin" or "obj" || name.StartsWith("bazel-", StringComparison.Ordinal) && Directory.Exists(path))
            {
                continue;
            }
            if (new FileInfo(path).LinkTarget is not null)
            {
                throw new InvalidDataException("NuGet update requires authored files without symlinks: " + path);
            }
            var target = Path.Combine(destination, name);
            if (Directory.Exists(path))
            {
                Directory.CreateDirectory(target);
                Copy(path, target, originals);
            }
            else
            {
                File.Copy(path, target);
                originals.Add(path, Digest(target));
            }
        }
    }

    private static void Publish(Dictionary<string, string> products)
    {
        var previous = products.Keys.ToDictionary(path => path, path => File.Exists(path) ? File.ReadAllText(path) : null);
        try
        {
            foreach (var (path, content) in products)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                File.WriteAllText(path, content);
            }
        }
        catch
        {
            foreach (var (path, content) in previous)
            {
                if (content is null)
                {
                    File.Delete(path);
                }
                else
                {
                    File.WriteAllText(path, content);
                }
            }
            throw;
        }
    }
}
