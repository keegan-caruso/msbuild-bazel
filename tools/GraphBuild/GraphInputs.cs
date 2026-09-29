using Microsoft.Build.Evaluation;
using Microsoft.Build.Execution;
using Microsoft.Build.Graph;

namespace RulesMSBuild.GraphBuild;

internal sealed class GraphInputs : IDisposable
{
    private readonly ProjectCollection collection;
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, string[]> imports = new(StringComparer.Ordinal);
    private readonly GraphContract contract;
    internal ContractFiles Files
    {
        get;
    }
    internal ProjectGraph Graph
    {
        get;
    }
    internal string SdkDigest
    {
        get;
    }
    internal ProjectCollection Collection => collection;

    internal GraphInputs(GraphContract contract, string root, string sdkRoot)
    {
        this.contract = contract;
        Files = new(root, sdkRoot);
        if (contract.Version != 1 || contract.Projects.Count == 0)
        {
            throw new InvalidDataException("Expected graph contract version 1 with explicit project inputs and outputs");
        }
        var sdk = Path.Combine(sdkRoot, "sdk", contract.SdkVersion);
        if (!Directory.Exists(sdk))
        {
            throw new InvalidDataException("Selected SDK is missing: " + contract.SdkVersion);
        }
        Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(sdk, "MSBuild.dll"));
        Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(sdk, "Sdks"));
        collection = new ProjectCollection();
        var properties = new Dictionary<string, string>(contract.Properties, StringComparer.OrdinalIgnoreCase);
        if (properties.ContainsKey("PathMap") || properties.ContainsKey("UseSharedCompilation"))
        {
            throw new InvalidDataException("PathMap and UseSharedCompilation are controlled by the graph runner");
        }
        properties["PathMap"] = Files.Root + "=/_/workspace," + Files.Sdk + "=/_/sdk";
        properties["UseSharedCompilation"] = "false";
        Graph = new ProjectGraph(new[] { new ProjectGraphEntryPoint(Files.Resolve(contract.Entry), properties) }, collection,
            (path, globals, projects) =>
            {
                var project = new Project(path, globals, null, projects);
                var instance = project.CreateProjectInstance();
                imports[Key(instance)] = project.Imports.Select(import => import.ImportedProject.FullPath).Distinct().ToArray();
                return instance;
            });
        foreach (var node in Graph.ProjectNodes)
        {
            Validate(node);
        }
        ValidateOutputOwnership();
        SdkDigest = ContractFiles.TreeDigest(sdkRoot);
    }

    internal ProjectContract For(ProjectGraphNode node) => contract.Projects.TryGetValue(Relative(node), out var value)
        ? value : throw new InvalidDataException("Missing project contract: " + Relative(node));
    internal string Relative(ProjectGraphNode node) => Path.GetRelativePath(Files.Root, node.ProjectInstance.FullPath);
    internal IEnumerable<string> OutputDirectories(ProjectGraphNode node) => For(node).OutputDirectories.Select(Files.Resolve);
    internal static string Key(ProjectInstance project) => project.FullPath + "|" + string.Join(";", project.GlobalProperties
        .OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => p.Key + "=" + p.Value));

    internal string Fingerprint(ProjectGraphNode node)
    {
        var project = node.ProjectInstance;
        var records = new List<string> { "graph-input-v1", Files.Root, Files.Sdk, SdkDigest, ContractFiles.Digest(typeof(GraphInputs).Assembly.Location), Relative(node) };
        records.AddRange(project.GlobalProperties.OrderBy(p => p.Key, StringComparer.Ordinal)
            .Select(p => p.Key + "=" + Files.Normalize(p.Value)));
        records.AddRange(For(node).OutputDirectories.Select(p => "output:" + p));
        records.Add("referenceBoundary:" + For(node).ReferenceBoundary);
        records.AddRange((For(node).DependencyCopies ?? []).OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => "copy:" + p.Key + "=" + p.Value));
        records.AddRange(contract.SharedInputs.Concat(For(node).Inputs).Distinct().Order(StringComparer.Ordinal)
            .Select(path => path + ":" + ContractFiles.Digest(Files.Resolve(path))));
        return ContractFiles.Hash(records);
    }

    private void Validate(ProjectGraphNode node)
    {
        var allowed = contract.SharedInputs.Concat(For(node).Inputs).Select(Files.Resolve).ToHashSet(StringComparer.Ordinal);
        Require(node.ProjectInstance.FullPath);
        foreach (var path in imports[Key(node.ProjectInstance)])
        {
            // SDK imports are covered by the SDK tree. NuGet-generated imports
            // must be explicitly declared just like authored props and targets.
            if (!path.StartsWith(Files.Sdk + Path.DirectorySeparatorChar, StringComparison.Ordinal))
            {
                Require(path);
            }
        }
        foreach (var kind in new[] { "Compile", "EmbeddedResource", "Content", "None", "AdditionalFiles", "Analyzer", "EditorConfigFiles", "GlobalAnalyzerConfigFiles" })
        {
            foreach (var item in node.ProjectInstance.GetItems(kind))
            {
                var path = Path.GetFullPath(item.EvaluatedInclude.Replace('\\', '/'), Path.GetDirectoryName(node.ProjectInstance.FullPath)!);
                if (File.Exists(path) && !path.StartsWith(Files.Sdk + Path.DirectorySeparatorChar, StringComparison.Ordinal))
                {
                    Require(path);
                }
            }
        }
        var assets = node.ProjectInstance.GetPropertyValue("ProjectAssetsFile");
        if (assets.Length != 0 && File.Exists(assets))
        {
            Require(assets);
        }
        foreach (var path in allowed)
        {
            if (!File.Exists(path))
            {
                throw new InvalidDataException("Declared graph input is missing: " + path);
            }
        }
        void Require(string path)
        {
            if (!allowed.Contains(path))
            {
                throw new InvalidDataException("Undeclared graph input for " + Relative(node) + ": " + Path.GetRelativePath(Files.Root, path));
            }
        }
    }

    private void ValidateOutputOwnership()
    {
        var directories = Graph.ProjectNodes.SelectMany(node => OutputDirectories(node).Select(path => (node, path))).ToArray();
        foreach (var (node, path) in directories)
        {
            if (directories.Any(other => other.node != node && (path == other.path || path.StartsWith(other.path + "/", StringComparison.Ordinal) || other.path.StartsWith(path + "/", StringComparison.Ordinal))))
            {
                throw new InvalidDataException("Overlapping output directories: " + path);
            }
            if (contract.SharedInputs.Concat(contract.Projects.Values.SelectMany(p => p.Inputs)).Any(input =>
                Files.Resolve(input).StartsWith(path + "/", StringComparison.Ordinal)))
            {
                throw new InvalidDataException("Output directory contains a declared input: " + path);
            }
        }
    }

    public void Dispose() => collection.Dispose();
}
