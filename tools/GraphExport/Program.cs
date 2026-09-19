using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Exceptions;
using Microsoft.Build.Execution;
using Microsoft.Build.Graph;

return await GraphExporter.RunAsync(args);

internal static class GraphExporter
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
    };

    // These request values are always replaced before evaluation. Persisting
    // them would leak ignored caller paths into an otherwise normalized graph.
    private static readonly HashSet<string> ExporterForcedGlobalProperties = new(StringComparer.OrdinalIgnoreCase)
    {
        "BazelGraphExport", "CustomAfterMicrosoftCommonTargets", "RestorePackagesPath",
    };

    private static readonly HashSet<string> InternalGlobalProperties = new(StringComparer.OrdinalIgnoreCase)
    {
        "BazelGraphExport", "CustomAfterMicrosoftCommonTargets", "RestorePackagesPath",
        "MSBuildProjectExtensionsPath", "IsGraphBuild", "CurrentSolutionConfigurationContents",
    };

    public static async Task<int> RunAsync(string[] args)
    {
        try
        {
            if (args.Length != 2 || args[0] != "--request")
                throw new ExportException("invalid-request", "usage: GraphExport --request <request.json>");

            var requestPath = Path.GetFullPath(args[1]);
            if (!File.Exists(requestPath))
                throw new ExportException("invalid-request", $"request does not exist: {requestPath}");

            var request = JsonSerializer.Deserialize<ExportRequest>(await File.ReadAllTextAsync(requestPath), JsonOptions)
                ?? throw new ExportException("invalid-request", "request is empty");
            ValidateRequest(request);
            ConfigureMsbuild(request);

            var manifest = Export(request);
            var serialized = JsonSerializer.Serialize(manifest, JsonOptions) + "\n";
            var output = Path.GetFullPath(request.Output);
            if (File.Exists(output) || Directory.Exists(output))
                throw new ExportException("output-exists", $"output already exists: {output}");
            Directory.CreateDirectory(Path.GetDirectoryName(output)!);
            var temp = output + ".tmp-" + Guid.NewGuid().ToString("N");
            await File.WriteAllTextAsync(temp, serialized, new UTF8Encoding(false));
            File.Move(temp, output);
            Console.WriteLine(JsonSerializer.Serialize(new { ok = true, schemaVersion = 1 }));
            return 0;
        }
        catch (ExportException ex)
        {
            Console.Error.WriteLine($"{ex.Code}: {ex.Message}");
            return 2;
        }
        catch (InvalidProjectFileException ex)
        {
            Console.Error.WriteLine($"project-evaluation: {ex.Message}");
            return 3;
        }
        catch (AggregateException ex) when (ex.Flatten().InnerExceptions.OfType<ExportException>().Any())
        {
            var failure = ex.Flatten().InnerExceptions.OfType<ExportException>().First();
            Console.Error.WriteLine($"{failure.Code}: {failure.Message}");
            return 2;
        }
        catch (AggregateException ex) when (ex.InnerExceptions.OfType<InvalidProjectFileException>().Any())
        {
            Console.Error.WriteLine($"project-evaluation: {ex.Flatten().InnerExceptions[0].Message}");
            return 3;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"internal-error: {ex}");
            return 4;
        }
    }

    private static void ValidateRequest(ExportRequest request)
    {
        if (request.SchemaVersion != 1 || request.EntryPoints is null || request.EntryPoints.Count == 0)
            throw new ExportException("invalid-request", "schemaVersion 1 and at least one entry point are required");
        request.Workspace = RequireDirectory(request.Workspace, "workspace");
        request.DotnetRoot = RequireDirectory(request.DotnetRoot, "dotnetRoot");
        request.PackageRoot = RequireDirectory(request.PackageRoot, "packageRoot");
        if (string.IsNullOrWhiteSpace(request.SdkVersion) || string.IsNullOrWhiteSpace(request.Output))
            throw new ExportException("invalid-request", "sdkVersion and output are required");

        foreach (var entry in request.EntryPoints)
        {
            entry.GlobalProperties ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            if (entry.GlobalProperties.TryGetValue("TargetFrameworks", out var tfms) && !string.IsNullOrWhiteSpace(tfms))
                throw new ExportException("unsupported-configuration", "multi-targeting is outside milestone 1");
            if ((entry.GlobalProperties.TryGetValue("RuntimeIdentifier", out var rid) && !string.IsNullOrWhiteSpace(rid)) ||
                (entry.GlobalProperties.TryGetValue("RuntimeIdentifiers", out var rids) && !string.IsNullOrWhiteSpace(rids)))
                throw new ExportException("unsupported-configuration", "RID builds are outside milestone 1");
            if (!entry.GlobalProperties.ContainsKey("Configuration"))
                entry.GlobalProperties["Configuration"] = "Release";
            var configuration = entry.GlobalProperties["Configuration"];
            if (configuration is not ("Release" or "Debug"))
                throw new ExportException("unsupported-configuration", $"unsupported Configuration={configuration}");
        }
    }

    private static string RequireDirectory(string value, string name)
    {
        if (string.IsNullOrWhiteSpace(value))
            throw new ExportException("invalid-request", $"{name} is required");
        var full = Path.GetFullPath(value);
        if (!Directory.Exists(full))
            throw new ExportException("missing-input", $"{name} does not exist: {full}");
        return full;
    }

    private static void ConfigureMsbuild(ExportRequest request)
    {
        var sdkRoot = Path.Combine(request.DotnetRoot, "sdk", request.SdkVersion);
        var msbuild = Path.Combine(sdkRoot, "MSBuild.dll");
        var sdks = Path.Combine(sdkRoot, "Sdks");
        if (!File.Exists(msbuild) || !Directory.Exists(sdks))
            throw new ExportException("missing-input", $"SDK {request.SdkVersion} is not present under dotnetRoot");
        System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (context, name) =>
        {
            var candidate = Path.Combine(sdkRoot, name.Name + ".dll");
            return File.Exists(candidate) ? context.LoadFromAssemblyPath(candidate) : null;
        };
        Environment.SetEnvironmentVariable("DOTNET_ROOT", request.DotnetRoot);
        Environment.SetEnvironmentVariable("DOTNET_HOST_PATH", Path.Combine(request.DotnetRoot, "dotnet"));
        Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", msbuild);
        Environment.SetEnvironmentVariable("MSBuildSDKsPath", sdks);
        Environment.SetEnvironmentVariable("NUGET_PACKAGES", request.PackageRoot);
    }

    private static Manifest Export(ExportRequest request)
    {
        var targets = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "Bazel.GraphExport.targets"));
        if (!File.Exists(targets))
            targets = Path.Combine(AppContext.BaseDirectory, "Bazel.GraphExport.targets");
        if (!File.Exists(targets))
            throw new ExportException("missing-input", "Bazel.GraphExport.targets is missing from the exporter payload");

        var entries = new List<ProjectGraphEntryPoint>();
        var entryRequests = new List<EntryRequest>();
        foreach (var entry in request.EntryPoints)
        {
            var project = ResolveWorkspacePath(request, entry.Project, "project");
            if (!File.Exists(project))
                throw new ExportException("missing-input", $"entry project does not exist: {entry.Project}");
            var props = new Dictionary<string, string>(entry.GlobalProperties!, StringComparer.OrdinalIgnoreCase)
            {
                ["BazelGraphExport"] = "true",
                ["CustomAfterMicrosoftCommonTargets"] = targets,
                ["RestorePackagesPath"] = request.PackageRoot,
            };
            entries.Add(new ProjectGraphEntryPoint(project, props));
            entryRequests.Add(new EntryRequest
            {
                Project = Rel(request.Workspace, project),
                GlobalProperties = entry.GlobalProperties!
                    .Where(pair => !ExporterForcedGlobalProperties.Contains(pair.Key))
                    .OrderBy(pair => pair.Key, StringComparer.Ordinal)
                    .ToDictionary(pair => pair.Key, pair => pair.Value),
            });
        }

        using var collection = new ProjectCollection();
        var graph = new ProjectGraph(entries, collection);
        var compilationNodes = graph.ProjectNodes.Where(IsCompilationNode).ToArray();
        if (compilationNodes.Any(node => node.ProjectInstance.GlobalProperties.ContainsKey("Flavor")) &&
            compilationNodes.Any(node => !string.Equals(node.ProjectInstance.GetPropertyValue("DisableTransitiveProjectReferences"), "true", StringComparison.OrdinalIgnoreCase)))
            throw new ExportException("unsupported-configured-transitive", "configured variants require the explicitly authored direct-edge graph");
        var ids = compilationNodes.ToDictionary(n => n, n => NodeId(request, n));

        // Resolve each disposable project instance in one action-local build
        // session. Recreating the engine for every node repeats SDK task loading
        // and teardown across the graph; no state survives this export.
        using var manager = new BuildManager();
        var discoveryLog = new StringBuilder();
        manager.BeginBuild(new BuildParameters { EnableNodeReuse = false, MaxNodeCount = 1, Loggers = [new Microsoft.Build.Logging.ConsoleLogger(Microsoft.Build.Framework.LoggerVerbosity.Minimal, text => discoveryLog.Append(text), null, null)] });
        List<NodeRecord> nodes;
        try
        {
            nodes = compilationNodes.Select(node => ExportNode(request, node, ids, manager, discoveryLog)).OrderBy(n => n.Project, StringComparer.Ordinal).ThenBy(n => n.Id, StringComparer.Ordinal).ToList();
        }
        finally { manager.EndBuild(); }
        PackageRestoreValidation.ValidateGraph(compilationNodes);
        var entryIds = new SortedSet<string>(StringComparer.Ordinal);
        foreach (var node in graph.EntryPointNodes)
            CollectEntryCompilationNodes(node, ids, entryIds);

        var graphInputs = new Dictionary<(string Kind, string Path), InputRecord>();
        foreach (var node in graph.ProjectNodes.Where(n => !IsCompilationNode(n)))
        {
            AddInput(request, graphInputs, "project", node.ProjectInstance.FullPath, workspaceOnly: true, normalizeText: false);
            foreach (var import in EnumerateImports(node.ProjectInstance))
                AddInput(request, graphInputs, "import", import, workspaceOnly: false, normalizeText: IsTextMetadata(import));
        }

        return new Manifest(
            1,
            new ToolchainRecord(request.SdkVersion, "ProjectGraph", 1),
            entryIds.ToList(),
            graphInputs.Values.OrderBy(i => i.Path, StringComparer.Ordinal).ThenBy(i => i.Kind, StringComparer.Ordinal).ToList(),
            nodes,
            entryRequests.OrderBy(entry => entry.Project, StringComparer.Ordinal)
                .ThenBy(entry => JsonSerializer.Serialize(entry.GlobalProperties, JsonOptions), StringComparer.Ordinal)
                .ToList());
    }

    private static NodeRecord ExportNode(ExportRequest request, ProjectGraphNode node, IReadOnlyDictionary<ProjectGraphNode, string> ids, BuildManager manager, StringBuilder discoveryLog)
    {
        var instance = node.ProjectInstance;
        ValidateSupported(instance);
        var inputs = new Dictionary<(string Kind, string Path), InputRecord>();
        AddInput(request, inputs, "project", instance.FullPath, workspaceOnly: true, normalizeText: false);
        foreach (var import in EnumerateImports(instance))
            AddInput(request, inputs, "import", import, workspaceOnly: false, normalizeText: IsTextMetadata(import));
        foreach (var gitInput in GitInputs.Discover(request.Workspace))
            AddInput(request, inputs, "extra", gitInput, workspaceOnly: true, normalizeText: false);

        var assets = instance.GetPropertyValue("ProjectAssetsFile");
        if (string.IsNullOrWhiteSpace(assets))
            assets = Path.Combine(Path.GetDirectoryName(instance.FullPath)!, "obj", "project.assets.json");
        if (!Path.IsPathRooted(assets))
            assets = Path.GetFullPath(assets, Path.GetDirectoryName(instance.FullPath)!);
        AddInput(request, inputs, "restore", assets, workspaceOnly: true, normalizeText: true);
        AddRestoreSidecar(request, inputs, assets, "project.nuget.cache");
        AddRestoreSidecar(request, inputs, assets, Path.GetFileNameWithoutExtension(instance.FullPath) + ".csproj.nuget.dgspec.json");

        PackageRestoreValidation.ValidateSuccessfulRestore(instance, assets);

        // Resolve SDK/package analyzer items in a disposable instance. No compilation
        // target runs, and the evaluated graph identity/restore contract stays intact.
        discoveryLog.Clear();
        var resolution = manager.PendBuildRequest(new BuildRequestData(instance.DeepCopy(), ["BazelGraphExportContract"], null,
            BuildRequestDataFlags.ProvideProjectStateAfterBuild)).Execute();
        if (resolution.OverallResult != BuildResultCode.Success || resolution.ProjectStateAfterBuild is null)
            throw new ExportException("input-discovery-failed", "SDK input resolution failed: " + instance.FullPath + "\n" + discoveryLog);
        var resolved = resolution.ProjectStateAfterBuild;
        // Framework processing adds implicit SDK PackageReferences (e.g. ILLink).
        // Restore checks must use those same evaluated SDK requests in every node.
        foreach (var item in instance.GetItems("PackageReference").ToArray()) instance.RemoveItem(item);
        foreach (var item in resolved.GetItems("PackageReference"))
            instance.AddItem("PackageReference", item.EvaluatedInclude,
                item.Metadata.Select(metadata => new KeyValuePair<string, string>(metadata.Name, metadata.EvaluatedValue)));
        if (string.Equals(instance.GetPropertyValue("SignAssembly"), "true", StringComparison.OrdinalIgnoreCase) &&
            string.IsNullOrWhiteSpace(instance.GetPropertyValue("AssemblyOriginatorKeyFile")))
            throw new ExportException("unsupported-signing", "signed builds require an explicit signing key file");
        foreach (var item in resolved.GetItems("_BazelExportInput"))
        {
            var kind = item.GetMetadataValue("Kind");
            if (string.IsNullOrWhiteSpace(kind)) kind = "extra";
            var path = item.GetMetadataValue("FullPath");
            if (string.IsNullOrWhiteSpace(path))
                path = Path.GetFullPath(item.EvaluatedInclude, Path.GetDirectoryName(instance.FullPath)!);
            var packageOwned = IsUnder(path, request.PackageRoot);
            if (packageOwned && kind is ("source" or "resource" or "content" or "additional"))
            {
                var packagePath = Rel(request.PackageRoot, path).Split('/');
                if (packagePath.Length < 3 || PilotPackagePolicy.Find(packagePath[0] + "/" + packagePath[1]) is null)
                    throw new ExportException("unsupported-package", "unqualified package-owned " + kind + ": " + path);
            }
            var workspaceOnly = kind is ("source" or "resource" or "content" or "additional" or "extra" or "signing" or "editorconfig") &&
                !(packageOwned && kind is ("source" or "resource" or "content" or "additional"));
            AddInput(request, inputs, kind, path, workspaceOnly: workspaceOnly, normalizeText: false);
            if (kind is "resource" or "additional" or "content")
            {
                var logical = NormalizeInputPath(request, path, workspaceOnly: workspaceOnly);
                var metadata = new SortedDictionary<string, string>(StringComparer.Ordinal);
                foreach (var name in new[] { "LogicalName", "ManifestResourceName", "Link", "DependentUpon", "WithCulture", "Culture", "TargetPath", "CopyToOutputDirectory", "CopyToPublishDirectory" })
                    if (item.GetMetadataValue(name) is { Length: > 0 } value) metadata[name] = value;
                inputs[(kind, logical)] = inputs[(kind, logical)] with { Metadata = metadata };
            }
        }

        using (var assetsDocument = JsonDocument.Parse(File.ReadAllText(assets)))
        {
            PackageRestoreValidation.Validate(instance, assetsDocument.RootElement);
            var restoreMetadata = assetsDocument.RootElement.GetProperty("project").GetProperty("restore");
            if (!restoreMetadata.TryGetProperty("outputPath", out var restoredOutput) ||
                CanonicalDirectory(restoredOutput.GetString()!) != CanonicalDirectory(Path.GetDirectoryName(assets)!))
                throw new ExportException("stale-restore", "configured restore output path differs from evaluated assets path: " + instance.FullPath);
            var frameworkPack = FrameworkPack.Selected(assetsDocument.RootElement, instance.GetPropertyValue("TargetFramework"));
            if (frameworkPack is not null)
            {
                var packRoot = Path.Combine(request.PackageRoot, frameworkPack.ToLowerInvariant());
                foreach (var payload in Directory.EnumerateFiles(packRoot, "*", SearchOption.AllDirectories).Where(file => !file.EndsWith(".nupkg.metadata", StringComparison.Ordinal)))
                    AddInput(request, inputs, "package", payload, workspaceOnly: false, normalizeText: false);
            }
            var selectedPackages = assetsDocument.RootElement.GetProperty("targets").GetProperty(instance.GetPropertyValue("TargetFramework"));
            foreach (var library in assetsDocument.RootElement.GetProperty("libraries").EnumerateObject())
            {
                if (library.Value.GetProperty("type").GetString() != "package" || !selectedPackages.TryGetProperty(library.Name, out _)) continue;
                var packagePath = library.Value.GetProperty("path").GetString()!;
                var folder = Path.GetFullPath(Path.Combine(request.PackageRoot, packagePath));
                if (!IsUnder(folder, request.PackageRoot))
                    throw new ExportException("path-escape", "package path escapes package root");
                foreach (var file in library.Value.GetProperty("files").EnumerateArray())
                {
                    var payload = Path.GetFullPath(Path.Combine(folder, file.GetString()!));
                    if (!IsUnder(payload, folder)) throw new ExportException("path-escape", "package file escapes package root");
                    AddInput(request, inputs, "package", payload, workspaceOnly: false, normalizeText: false);
                }
                var identity = library.Name.Split('/');
                AddInput(request, inputs, "package", Path.Combine(folder,
                    identity[0].ToLowerInvariant() + "." + identity[1] + ".nupkg"),
                    workspaceOnly: false, normalizeText: false);
            }
        }

        var outputs = new Dictionary<(string Kind, string Path), OutputRecord>();
        foreach (var item in instance.GetItems("_BazelExportOutput"))
        {
            var include = item.EvaluatedInclude;
            if (string.IsNullOrWhiteSpace(include)) continue;
            var path = item.GetMetadataValue("FullPath");
            if (string.IsNullOrWhiteSpace(path))
                path = Path.GetFullPath(include, Path.GetDirectoryName(instance.FullPath)!);
            AddOutput(request, outputs, item.GetMetadataValue("Kind") is { Length: > 0 } k ? k : "extra", path);
        }
        if (outputs.Count == 0)
        {
            var targetPath = instance.GetPropertyValue("TargetPath");
            if (!string.IsNullOrWhiteSpace(targetPath))
                AddOutput(request, outputs, "assembly", targetPath);
        }

        var directReferencePaths = instance.GetItems("ProjectReference")
            .Select(item => item.GetMetadataValue("FullPath"))
            .Where(path => !string.IsNullOrWhiteSpace(path))
            .Select(Path.GetFullPath)
            .ToHashSet(OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal);
        var dependencies = node.ProjectReferences
            .Where(IsCompilationNode)
            .Where(reference => directReferencePaths.Contains(Path.GetFullPath(reference.ProjectInstance.FullPath)))
            .Select(reference => ids[reference])
            .OrderBy(id => id, StringComparer.Ordinal)
            .ToList();
        var globalProperties = NormalizedGlobalProperties(instance);
        return new NodeRecord(
            ids[node],
            NormalizeWorkspaceRelative(request, instance.FullPath),
            globalProperties,
            instance.GetPropertyValue("TargetFramework"),
            instance.GetPropertyValue("OutputType"),
            dependencies,
            inputs.Values.OrderBy(i => i.Path, StringComparer.Ordinal).ThenBy(i => i.Kind, StringComparer.Ordinal).ToList(),
            outputs.Values.OrderBy(o => o.Path, StringComparer.Ordinal).ThenBy(o => o.Kind, StringComparer.Ordinal).ToList(),
            new ExecutionRecord(NormalizeWorkspaceRelative(request, assets),
                NormalizeWorkspaceRelative(request, Path.GetDirectoryName(instance.GetPropertyValue("TargetPath"))!),
                NormalizeWorkspaceRelative(request, Path.GetFullPath(Path.Combine(instance.GetPropertyValue("IntermediateOutputPath"), "ref"), Path.GetDirectoryName(instance.FullPath)!)),
                node.ProjectInstance.GetItems("ProjectReference")
                    .Where(reference => !string.IsNullOrEmpty(reference.GetMetadataValue("SetTargetFramework")))
                    .Select(reference => new SelectedReferenceRecord(
                        NormalizeWorkspaceRelative(request, reference.GetMetadataValue("FullPath")),
                        SelectedFramework(reference.GetMetadataValue("SetTargetFramework"))))
                    .OrderBy(reference => reference.Project, StringComparer.Ordinal).ToList(),
                instance.GetItems("ProjectReference").Where(reference => reference.GetMetadataValue("OutputItemType").Equals("Analyzer", StringComparison.OrdinalIgnoreCase) &&
                    reference.GetMetadataValue("ReferenceOutputAssembly").Equals("false", StringComparison.OrdinalIgnoreCase))
                    .Select(reference => NormalizeWorkspaceRelative(request, reference.GetMetadataValue("FullPath"))).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToList()),
            new DiscoveryRecord(instance.GetPropertyValue("SignAssembly").Equals("true", StringComparison.OrdinalIgnoreCase),
                instance.GetPropertyValue("PublicSign").Equals("true", StringComparison.OrdinalIgnoreCase),
                instance.GetPropertyValue("DelaySign").Equals("true", StringComparison.OrdinalIgnoreCase)));
    }

    private static string SelectedFramework(string metadata)
    {
        const string prefix = "TargetFramework=";
        if (!metadata.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) ||
            metadata.Length == prefix.Length || metadata.Contains(';'))
            throw new ExportException("unsupported-configured-reference", "unexpected SDK framework selection: " + metadata);
        return metadata[prefix.Length..];
    }

    internal static string CanonicalDirectory(string path)
    {
        var full = Path.GetFullPath(path);
        var current = Path.GetPathRoot(full)!;
        foreach (var segment in full[current.Length..].Split(Path.DirectorySeparatorChar, StringSplitOptions.RemoveEmptyEntries))
        {
            var directory = new DirectoryInfo(Path.Combine(current, segment));
            current = directory.Exists ? directory.ResolveLinkTarget(true)?.FullName ?? directory.FullName : directory.FullName;
        }
        return current.TrimEnd(Path.DirectorySeparatorChar);
    }

    private static void ValidateSupported(Microsoft.Build.Execution.ProjectInstance instance)
    {
        var frameworks = instance.GetPropertyValue("TargetFrameworks");
        if (!string.IsNullOrWhiteSpace(frameworks) &&
            (!instance.GlobalProperties.TryGetValue("TargetFramework", out var selected) ||
             !frameworks.Split(';', StringSplitOptions.TrimEntries).Contains(selected, StringComparer.OrdinalIgnoreCase)))
            throw new ExportException("unsupported-configuration", $"unselected or invalid multi-targeting inner build: {instance.FullPath}");
        if (!string.IsNullOrWhiteSpace(instance.GetPropertyValue("RuntimeIdentifier")) || !string.IsNullOrWhiteSpace(instance.GetPropertyValue("RuntimeIdentifiers")))
            throw new ExportException("unsupported-configuration", $"RID build: {instance.FullPath}");
        var tfm = instance.GetPropertyValue("TargetFramework");
        if (tfm is not ("net10.0" or "net8.0" or "netstandard2.0"))
            throw new ExportException("unsupported-configuration", $"TargetFramework {tfm} is outside the selected framework slice: {instance.FullPath}");
        var configuration = instance.GetPropertyValue("Configuration");
        if (configuration is not ("Release" or "Debug"))
            throw new ExportException("unsupported-configuration", $"Configuration {configuration}: {instance.FullPath}");
    }

    private static bool IsCompilationNode(ProjectGraphNode node) =>
        string.Equals(Path.GetExtension(node.ProjectInstance.FullPath), ".csproj", StringComparison.OrdinalIgnoreCase);

    private static void CollectEntryCompilationNodes(ProjectGraphNode node, IReadOnlyDictionary<ProjectGraphNode, string> ids, ISet<string> result)
    {
        if (IsCompilationNode(node))
        {
            result.Add(ids[node]);
            return;
        }
        foreach (var reference in node.ProjectReferences)
            CollectEntryCompilationNodes(reference, ids, result);
    }

    private static SortedDictionary<string, string> NormalizedGlobalProperties(Microsoft.Build.Execution.ProjectInstance instance)
    {
        var result = new SortedDictionary<string, string>(StringComparer.Ordinal);
        foreach (var pair in instance.GlobalProperties)
        {
            if (InternalGlobalProperties.Contains(pair.Key)) continue;
            result[pair.Key.ToLowerInvariant()] = pair.Value;
        }
        return result;
    }

    private static string NodeId(ExportRequest request, ProjectGraphNode node)
    {
        var project = NormalizeWorkspaceRelative(request, node.ProjectInstance.FullPath);
        var props = NormalizedGlobalProperties(node.ProjectInstance);
        var identity = project + "\n" + string.Join("\n", props.Select(p => p.Key + "=" + p.Value));
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(identity))).ToLowerInvariant()[..24];
    }

    private static IEnumerable<string> EnumerateImports(Microsoft.Build.Execution.ProjectInstance instance)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        // MSBuildAllProjects is an incremental-build property, not a complete import
        // inventory. ImportPaths records the evaluated conditional/nested closure.
        var all = instance.GetPropertyValue("MSBuildAllProjects");
        foreach (var raw in instance.ImportPaths.Concat(all.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)))
        {
            var path = raw;
            if (!Path.IsPathRooted(path)) path = Path.GetFullPath(path, Path.GetDirectoryName(instance.FullPath)!);
            path = Path.GetFullPath(path);
            var fileName = Path.GetFileName(path);
            if (fileName.EndsWith(".nuget.g.props", StringComparison.OrdinalIgnoreCase) ||
                fileName.EndsWith(".nuget.g.targets", StringComparison.OrdinalIgnoreCase))
                continue;
            if (File.Exists(path) && !string.Equals(path, Path.GetFullPath(instance.FullPath), StringComparison.Ordinal) && seen.Add(path))
                yield return path;
        }
    }

    private static void AddRestoreSidecar(ExportRequest request, IDictionary<(string Kind, string Path), InputRecord> inputs, string assets, string name)
    {
        var path = Path.Combine(Path.GetDirectoryName(assets)!, name);
        if (File.Exists(path)) AddInput(request, inputs, "restore", path, workspaceOnly: true, normalizeText: true);
    }

    private static void AddInput(ExportRequest request, IDictionary<(string Kind, string Path), InputRecord> inputs, string kind, string path, bool workspaceOnly, bool normalizeText)
    {
        path = Path.GetFullPath(path);
        if (!File.Exists(path)) throw new ExportException("missing-input", $"{kind} input does not exist: {path}");
        EnsureNoSymlinkEscape(request, path, workspaceOnly);
        var logical = NormalizeInputPath(request, path, workspaceOnly);
        if (logical.StartsWith("nix/", StringComparison.Ordinal) && kind != "import")
            throw new ExportException("path-escape", "external Nix inputs are limited to evaluated imports");
        var info = new FileInfo(path);
        var stamp = (info.Length, info.LastWriteTimeUtc.Ticks, info.CreationTimeUtc.Ticks, info.Attributes);
        var key = (path, normalizeText);
        string hash;
        if (request.InputHashes.TryGetValue(key, out var cached))
        {
            if (cached.Stamp != stamp) throw new ExportException("input-changed", "input changed during export: " + path);
            hash = cached.Hash;
        }
        else
        {
            hash = normalizeText ? HashNormalizedText(request, path) : HashFile(path);
            info.Refresh();
            if (stamp != (info.Length, info.LastWriteTimeUtc.Ticks, info.CreationTimeUtc.Ticks, info.Attributes)) throw new ExportException("input-changed", "input changed while hashing: " + path);
            request.InputHashes.Add(key, (stamp, hash));
        }
        inputs[(kind, logical)] = new InputRecord(kind, logical, hash);
    }

    private static void AddOutput(ExportRequest request, IDictionary<(string Kind, string Path), OutputRecord> outputs, string kind, string path)
    {
        path = Path.GetFullPath(path);
        if (!IsUnder(path, request.Workspace)) throw new ExportException("path-escape", $"output escapes workspace: {path}");
        var logical = NormalizeWorkspaceRelative(request, path);
        outputs[(kind, logical)] = new OutputRecord(kind, logical);
    }

    private static string NormalizeInputPath(ExportRequest request, string path, bool workspaceOnly)
    {
        if (IsUnder(path, request.Workspace)) return NormalizeWorkspaceRelative(request, path);
        if (workspaceOnly) throw new ExportException("path-escape", $"input escapes workspace: {path}");
        if (IsUnder(path, request.PackageRoot)) return "packages/" + Rel(request.PackageRoot, path);
        if (IsUnder(path, request.DotnetRoot)) return "dotnet/" + Rel(request.DotnetRoot, path);
        var adapter = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", ".."));
        if (IsUnder(path, adapter)) return "adapter/" + Rel(adapter, path);
        if (IsUnder(request.DotnetRoot, "/nix/store") && IsUnder(path, "/nix/store"))
            return "nix/" + Rel("/nix/store", path);
        throw new ExportException("path-escape", $"undeclared host input: {path}");
    }

    private static string NormalizeWorkspaceRelative(ExportRequest request, string path)
    {
        path = Path.GetFullPath(path);
        if (!IsUnder(path, request.Workspace)) throw new ExportException("path-escape", $"path escapes workspace: {path}");
        return "workspace/" + Rel(request.Workspace, path);
    }

    private static string Rel(string root, string path) => Path.GetRelativePath(root, path).Replace('\\', '/');

    private static bool IsUnder(string path, string root)
    {
        path = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        root = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        return path.StartsWith(root, OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal);
    }

    private static string ResolveWorkspacePath(ExportRequest request, string relative, string kind)
    {
        if (string.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative))
            throw new ExportException("path-escape", $"{kind} must be workspace-relative: {relative}");
        var full = Path.GetFullPath(relative, request.Workspace);
        if (!IsUnder(full, request.Workspace)) throw new ExportException("path-escape", $"{kind} escapes workspace: {relative}");
        EnsureNoSymlinkEscape(request, full, workspaceOnly: true);
        return full;
    }

    private static void EnsureNoSymlinkEscape(ExportRequest request, string path, bool workspaceOnly)
    {
        var info = new FileInfo(path);
        if (info.LinkTarget is null) return;
        var resolved = info.ResolveLinkTarget(true)?.FullName;
        if (resolved is null) throw new ExportException("missing-input", $"broken symlink: {path}");
        if (workspaceOnly && !IsUnder(resolved, request.Workspace))
            throw new ExportException("path-escape", $"symlink escapes workspace: {path} -> {resolved}");
        if (!workspaceOnly && !(IsUnder(resolved, request.Workspace) || IsUnder(resolved, request.PackageRoot) || IsUnder(resolved, request.DotnetRoot)))
            throw new ExportException("path-escape", $"symlink reaches undeclared host path: {path} -> {resolved}");
    }

    private static bool IsTextMetadata(string path)
    {
        var ext = Path.GetExtension(path).ToLowerInvariant();
        return ext is ".json" or ".props" or ".targets" or ".xml" or ".proj" or ".csproj";
    }

    private static string HashNormalizedText(ExportRequest request, string path)
    {
        var text = File.ReadAllText(path);
        text = ReplaceRoot(text, request.Workspace, "$WORKSPACE");
        text = ReplaceRoot(text, request.PackageRoot, "$PACKAGES");
        text = ReplaceRoot(text, request.DotnetRoot, "$DOTNET");
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text))).ToLowerInvariant();
    }

    private static string ReplaceRoot(string text, string root, string token)
    {
        text = text.Replace(root, token, StringComparison.Ordinal);
        return text.Replace(root.Replace('\\', '/'), token, StringComparison.Ordinal);
    }

    private static string HashFile(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }
}

internal sealed class ExportException(string code, string message) : Exception(message)
{
    public string Code { get; } = code;
}

internal sealed class ExportRequest
{
    // One export only: normalized and raw views remain distinct, and every
    // reference still passes path validation and checks the observed file stamp.
    internal Dictionary<(string Path, bool Normalized), ((long Length, long Modified, long Created, FileAttributes Attributes) Stamp, string Hash)> InputHashes { get; } = [];
    public int SchemaVersion { get; set; }
    public string Workspace { get; set; } = "";
    public string DotnetRoot { get; set; } = "";
    public string SdkVersion { get; set; } = "";
    public string PackageRoot { get; set; } = "";
    public List<EntryRequest> EntryPoints { get; set; } = [];
    public string Output { get; set; } = "";
}

internal sealed class EntryRequest
{
    public string Project { get; set; } = "";
    public Dictionary<string, string>? GlobalProperties { get; set; }
}

internal sealed record ToolchainRecord(string SdkVersion, string GraphEngine, int ContractVersion);
internal sealed record InputRecord(string Kind, string Path, string Sha256, SortedDictionary<string, string>? Metadata = null);
internal sealed record OutputRecord(string Kind, string Path);
internal sealed record NodeRecord(string Id, string Project, SortedDictionary<string, string> GlobalProperties, string TargetFramework, string OutputType, List<string> Dependencies, List<InputRecord> Inputs, List<OutputRecord> Outputs, ExecutionRecord Execution, DiscoveryRecord Discovery);
internal sealed record SelectedReferenceRecord(string Project, string TargetFramework);
internal sealed record ExecutionRecord(string AssetsFile, string OutputDirectory, string ReferenceDirectory, List<SelectedReferenceRecord> SelectedReferences, List<string>? AnalyzerReferences = null);
internal sealed record Manifest(int SchemaVersion, ToolchainRecord Toolchain, List<string> EntryPoints, List<InputRecord> GraphInputs, List<NodeRecord> Nodes, List<EntryRequest> EntryRequests);

internal sealed record DiscoveryRecord(bool SignAssembly, bool PublicSign, bool DelaySign);
