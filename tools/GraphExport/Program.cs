using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Exceptions;
using Microsoft.Build.Graph;

return await GraphExporter.RunAsync(args);

internal static class GraphExporter
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        WriteIndented = true,
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
        }

        using var collection = new ProjectCollection();
        var graph = new ProjectGraph(entries, collection);
        var compilationNodes = graph.ProjectNodes.Where(IsCompilationNode).ToArray();
        var ids = compilationNodes.ToDictionary(n => n, n => NodeId(request, n));

        var nodes = compilationNodes.Select(node => ExportNode(request, node, ids)).OrderBy(n => n.Project, StringComparer.Ordinal).ThenBy(n => n.Id, StringComparer.Ordinal).ToList();
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
            nodes);
    }

    private static NodeRecord ExportNode(ExportRequest request, ProjectGraphNode node, IReadOnlyDictionary<ProjectGraphNode, string> ids)
    {
        var instance = node.ProjectInstance;
        ValidateSupported(instance);
        var inputs = new Dictionary<(string Kind, string Path), InputRecord>();
        AddInput(request, inputs, "project", instance.FullPath, workspaceOnly: true, normalizeText: false);
        foreach (var import in EnumerateImports(instance))
            AddInput(request, inputs, "import", import, workspaceOnly: false, normalizeText: IsTextMetadata(import));

        foreach (var item in instance.GetItems("_BazelExportInput"))
        {
            var kind = item.GetMetadataValue("Kind");
            if (string.IsNullOrWhiteSpace(kind)) kind = "extra";
            var path = item.GetMetadataValue("FullPath");
            if (string.IsNullOrWhiteSpace(path))
                path = Path.GetFullPath(item.EvaluatedInclude, Path.GetDirectoryName(instance.FullPath)!);
            AddInput(request, inputs, kind, path, workspaceOnly: kind is "source" or "resource" or "content" or "additional" or "extra", normalizeText: false);
        }

        var assets = instance.GetPropertyValue("ProjectAssetsFile");
        if (string.IsNullOrWhiteSpace(assets))
            assets = Path.Combine(Path.GetDirectoryName(instance.FullPath)!, "obj", "project.assets.json");
        if (!Path.IsPathRooted(assets))
            assets = Path.GetFullPath(assets, Path.GetDirectoryName(instance.FullPath)!);
        AddInput(request, inputs, "restore", assets, workspaceOnly: true, normalizeText: true);
        AddRestoreSidecar(request, inputs, assets, "project.nuget.cache");
        AddRestoreSidecar(request, inputs, assets, Path.GetFileNameWithoutExtension(instance.FullPath) + ".csproj.nuget.dgspec.json");

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

        var dependencies = node.ProjectReferences.Where(IsCompilationNode).Select(n => ids[n]).OrderBy(x => x, StringComparer.Ordinal).ToList();
        var globalProperties = NormalizedGlobalProperties(instance);
        return new NodeRecord(
            ids[node],
            NormalizeWorkspaceRelative(request, instance.FullPath),
            globalProperties,
            instance.GetPropertyValue("TargetFramework"),
            instance.GetPropertyValue("OutputType"),
            dependencies,
            inputs.Values.OrderBy(i => i.Path, StringComparer.Ordinal).ThenBy(i => i.Kind, StringComparer.Ordinal).ToList(),
            outputs.Values.OrderBy(o => o.Path, StringComparer.Ordinal).ThenBy(o => o.Kind, StringComparer.Ordinal).ToList());
    }

    private static void ValidateSupported(Microsoft.Build.Execution.ProjectInstance instance)
    {
        if (!string.IsNullOrWhiteSpace(instance.GetPropertyValue("TargetFrameworks")))
            throw new ExportException("unsupported-configuration", $"multi-targeting: {instance.FullPath}");
        if (!string.IsNullOrWhiteSpace(instance.GetPropertyValue("RuntimeIdentifier")) || !string.IsNullOrWhiteSpace(instance.GetPropertyValue("RuntimeIdentifiers")))
            throw new ExportException("unsupported-configuration", $"RID build: {instance.FullPath}");
        var tfm = instance.GetPropertyValue("TargetFramework");
        if (!string.Equals(tfm, "net10.0", StringComparison.OrdinalIgnoreCase))
            throw new ExportException("unsupported-configuration", $"TargetFramework {tfm} is outside milestone 1: {instance.FullPath}");
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
        var all = instance.GetPropertyValue("MSBuildAllProjects");
        foreach (var raw in all.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var path = raw;
            if (!Path.IsPathRooted(path)) path = Path.GetFullPath(path, Path.GetDirectoryName(instance.FullPath)!);
            if (File.Exists(path) && !string.Equals(Path.GetFullPath(path), Path.GetFullPath(instance.FullPath), StringComparison.Ordinal) && seen.Add(Path.GetFullPath(path)))
                yield return Path.GetFullPath(path);
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
        var hash = normalizeText ? HashNormalizedText(request, path) : HashFile(path);
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
internal sealed record InputRecord(string Kind, string Path, string Sha256);
internal sealed record OutputRecord(string Kind, string Path);
internal sealed record NodeRecord(string Id, string Project, SortedDictionary<string, string> GlobalProperties, string TargetFramework, string OutputType, List<string> Dependencies, List<InputRecord> Inputs, List<OutputRecord> Outputs);
internal sealed record Manifest(int SchemaVersion, ToolchainRecord Toolchain, List<string> EntryPoints, List<InputRecord> GraphInputs, List<NodeRecord> Nodes);
