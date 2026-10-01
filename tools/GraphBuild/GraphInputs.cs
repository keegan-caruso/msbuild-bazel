using Microsoft.Build.Definition;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Evaluation.Context;
using Microsoft.Build.Execution;
using Microsoft.Build.Graph;

namespace RulesMSBuild.GraphBuild;

internal sealed class GraphInputs : IDisposable
{
    private readonly ProjectCollection collection;
    private readonly Dictionary<string, ProjectGraphNode> directoryOwners;
    private readonly Dictionary<string, ProjectGraphNode> fileOwners;
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, string[]> imports = new(StringComparer.Ordinal);
    private readonly GraphContract contract;
    private readonly Dictionary<string, string> inputDigests;
    private readonly bool readOnlyPackages;
    private readonly Dictionary<string, string> resolvedInputs;
    private readonly string runnerDigest;
    private readonly string sharedDigest;
    private readonly Dictionary<ProjectGraphNode, string> dependencyFingerprints;
    private readonly HashSet<string> sharedPaths;
    private readonly Dictionary<string, string[]> packagePathAliases;
    private readonly Dictionary<ProjectGraphNode, string> baseFingerprints;
    private readonly Dictionary<ProjectGraphNode, ProjectContract> projects = [];
    internal double EvaluationSeconds
    {
        get;
    }
    internal double InputHashSeconds
    {
        get;
    }
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

    internal GraphInputs(GraphContract contract, string root, string sdkRoot, bool restored = false, RestoredInputs? prepared = null)
    {
        var timer = System.Diagnostics.Stopwatch.StartNew();
        this.contract = contract;
        Files = new(root, sdkRoot);
        sharedPaths = Files.ResolveInputs(contract.SharedInputs).Values.ToHashSet(StringComparer.Ordinal);
        packagePathAliases = sharedPaths.Where(path => path.StartsWith(Path.Combine(Files.Root, ".nuget") + Path.DirectorySeparatorChar, StringComparison.Ordinal))
            .GroupBy(path => path, StringComparer.OrdinalIgnoreCase).ToDictionary(group => group.Key, group => group.ToArray(), StringComparer.OrdinalIgnoreCase);
        foreach (var path in sharedPaths)
        {
            if (!File.Exists(path))
            {
                throw new InvalidDataException("Declared graph input is missing: " + path);
            }
        }
        if (contract.Version is not (1 or 2 or 3 or 4 or 5 or 6) || contract.Projects.Count == 0)
        {
            throw new InvalidDataException("Expected graph contract version 1, 2, 3, 4, 5 or 6 with explicit project inputs and outputs");
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
        if (properties.ContainsKey("PathMap") || properties.ContainsKey("UseSharedCompilation") || properties.ContainsKey("NetCoreSdkRoot") || properties.ContainsKey("DOTNET_HOST_PATH"))
        {
            throw new InvalidDataException("SDK host paths, PathMap and UseSharedCompilation are controlled by the graph runner");
        }
        properties["PathMap"] = Files.Root + "=/_/workspace," + Files.Sdk + "=/_/sdk";
        properties["UseSharedCompilation"] = "false";
        properties["NetCoreSdkRoot"] = sdk;
        var evaluationContext = EvaluationContext.Create(EvaluationContext.SharingPolicy.Shared);
        using (GraphProfile.Measure("projectEvaluation"))
        {
            Graph = new ProjectGraph((contract.Entries ?? [contract.Entry]).Select(entry => new ProjectGraphEntryPoint(Files.Resolve(entry), GraphEntryProperties.For(entry, properties, contract.EntryProperties ?? []))), collection,
                (path, globals, projects) =>
                {
                    var project = Project.FromFile(path, new ProjectOptions
                    {
                        GlobalProperties = globals,
                        ProjectCollection = projects,
                        // Graph builds do not need IDE-only items from inactive conditions.
                        LoadSettings = ProjectLoadSettings.DoNotEvaluateElementsWithFalseCondition,
                        EvaluationContext = evaluationContext
                    });
                    var instance = project.CreateProjectInstance();
                    imports[Key(instance)] = project.Imports.Select(import => import.ImportedProject.FullPath).Distinct().ToArray();
                    return instance;
                });
        }
        foreach (var node in Graph.ProjectNodes)
        {
            projects.Add(node, restored ? RestoreInputs(node, Select(node)) : Select(node));
        }
        readOnlyPackages = prepared?.ReadOnlyPackages == true;
        resolvedInputs = Files.ResolveInputs(contract.SharedInputs.Concat(projects.Values.SelectMany(p => p.Inputs)));
        foreach (var node in Graph.ProjectNodes)
        {
            Validate(node);
        }
        ValidateOutputOwnership();
        // Ownership is immutable contract metadata. Actual reads/writes still
        // resolve their paths to reject symlinks introduced during execution.
        directoryOwners = Graph.ProjectNodes.SelectMany(node => OutputDirectories(node).Select(path => (path, node)))
            .GroupBy(pair => pair.path, StringComparer.Ordinal).ToDictionary(group => group.Key, group => group.First().node, StringComparer.Ordinal);
        fileOwners = Graph.ProjectNodes.SelectMany(node => DeclaredOutputFiles(node).Select(path => (path, node)))
            .GroupBy(pair => pair.path, StringComparer.Ordinal).ToDictionary(group => group.Key, group => group.First().node, StringComparer.Ordinal);
        EvaluationSeconds = timer.Elapsed.TotalSeconds;
        timer.Restart();
        using (GraphProfile.Measure("sdkHash"))
        {
            SdkDigest = prepared?.SdkDigest ?? ContractFiles.TreeDigest(sdkRoot);
        }
        runnerDigest = ContractFiles.Digest(typeof(GraphInputs).Assembly.Location);
        inputDigests = resolvedInputs.ToDictionary(pair => pair.Key, pair => prepared?.Digests.GetValueOrDefault(pair.Key) ?? ContractFiles.InputDigest(pair.Value), StringComparer.Ordinal);
        sharedDigest = ContractFiles.Hash(contract.SharedInputs.Distinct().Order(StringComparer.Ordinal).Select(path => path + ":" + inputDigests[path]));
        baseFingerprints = [];
        dependencyFingerprints = [];
        foreach (var node in Graph.ProjectNodes)
        {
            ComputeFingerprints(node);
        }
        InputHashSeconds = timer.Elapsed.TotalSeconds;
    }

    internal ProjectContract For(ProjectGraphNode node) => projects[node];

    private ProjectContract Select(ProjectGraphNode node)
    {
        if (!contract.Projects.TryGetValue(Relative(node), out var project))
        {
            throw new InvalidDataException("Missing project contract: " + Relative(node));
        }
        if (project.Configurations is null)
        {
            return project;
        }
        if (contract.Version is not (2 or 3 or 4 or 5 or 6) || project.OutputDirectories.Length != 0 || project.OutputFiles?.Length > 0 || project.ReferenceBoundary || project.DependencyCopies?.Count > 0 || project.ImplementationDependencies?.Length > 0)
        {
            throw new InvalidDataException("Configured projects require version 2, 3, 4, 5 or 6 and configuration-owned outputs: " + Relative(node));
        }
        var matches = project.Configurations.Where(configuration => configuration.Properties.Count != 0 &&
            configuration.Properties.All(property =>
                (node.ProjectInstance.GlobalProperties.TryGetValue(property.Key, out var value) ? value : "") == property.Value)).ToArray();
        if (matches.Length != 1)
        {
            throw new InvalidDataException("Expected exactly one configuration contract for " + Key(node.ProjectInstance) + "; matched " + matches.Length);
        }
        var selected = matches[0];
        return new ProjectContract(project.Inputs.Concat(selected.Inputs).Distinct().ToArray(),
            selected.OutputDirectories, selected.ReferenceBoundary, selected.DependencyCopies, OutputFiles: selected.OutputFiles, ImplementationDependencies: selected.ImplementationDependencies);
    }
    private ProjectContract RestoreInputs(ProjectGraphNode node, ProjectContract project)
    {
        var instance = node.ProjectInstance;
        var assets = instance.GetPropertyValue("ProjectAssetsFile");
        var extensions = instance.GetPropertyValue("MSBuildProjectExtensionsPath");
        // Traversal projects may not use NuGet at all.
        if (assets.Length == 0 && extensions.Length == 0)
        {
            return project;
        }
        var directory = Path.GetDirectoryName(instance.FullPath)!;
        var generated = new[]
        {
            Path.GetFullPath(assets, directory),
            Path.Combine(Path.GetFullPath(extensions, directory), Path.GetFileName(instance.FullPath) + ".nuget.g.props"),
            Path.Combine(Path.GetFullPath(extensions, directory), Path.GetFileName(instance.FullPath) + ".nuget.g.targets"),
        };
        var relative = generated.Select(path => Path.GetRelativePath(Files.Root, path)).ToArray();
        foreach (var path in relative)
        {
            if (!File.Exists(Files.Resolve(path)))
            {
                throw new InvalidDataException("Missing evaluated graph Restore output: " + path);
            }
        }
        var diagnostics = new[] { Path.GetFileName(instance.FullPath) + ".nuget.dgspec.json", "project.nuget.cache" }
            .Select(name => Path.Combine(Path.GetFullPath(extensions, directory), name))
            .Where(File.Exists).Select(path => Path.GetRelativePath(Files.Root, path));
        return project with
        {
            Inputs = project.Inputs.Concat(relative).Concat(diagnostics).Distinct().ToArray()
        };
    }

    internal string Relative(ProjectGraphNode node) => Path.GetRelativePath(Files.Root, node.ProjectInstance.FullPath);
    internal IEnumerable<string> OutputDirectories(ProjectGraphNode node) => For(node).OutputDirectories.Select(Files.Resolve);
    internal IEnumerable<string> DeclaredOutputFiles(ProjectGraphNode node) => (For(node).OutputFiles ?? []).Select(Files.Resolve);
    internal bool OwnsOutput(ProjectGraphNode node, string path) => OutputOwner(path) == node;
    internal ProjectGraphNode? OutputOwner(string path)
    {
        if (fileOwners.TryGetValue(path, out var owner))
        {
            return owner;
        }
        for (var directory = Path.GetDirectoryName(path); directory is not null && directory != Files.Root; directory = Path.GetDirectoryName(directory))
        {
            if (directoryOwners.TryGetValue(directory, out owner))
            {
                return owner;
            }
        }
        return null;
    }
    internal static string Key(ProjectInstance project) => project.FullPath + "|" + string.Join(";", project.GlobalProperties
        .OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => p.Key + "=" + p.Value));

    internal string Fingerprint(ProjectGraphNode node) => baseFingerprints[node];

    internal string DependencyFingerprint(ProjectGraphNode node) => dependencyFingerprints[node];

    private void ComputeFingerprints(ProjectGraphNode node)
    {
        var project = node.ProjectInstance;
        var records = new List<string> { "graph-input-v2", Files.Root, Files.Sdk, SdkDigest, runnerDigest, sharedDigest, Relative(node) };
        records.AddRange((contract.TemporaryDirectories ?? []).Order(StringComparer.Ordinal).Select(path => "temporary-directory:" + path));
        records.AddRange((contract.InputDirectories ?? []).Order(StringComparer.Ordinal).Select(path => "input-directory:" + path));
        records.AddRange(project.Properties.OrderBy(p => p.Name, StringComparer.Ordinal)
            .Select(p => p.Name + "=" + p.EvaluatedValue));
        records.AddRange(project.Items.Select(item => System.Text.Json.JsonSerializer.Serialize(new
        {
            item.ItemType,
            item.EvaluatedInclude,
            metadata = item.Metadata.OrderBy(m => m.Name, StringComparer.Ordinal).Select(m => new { m.Name, m.EvaluatedValue }).ToArray(),
        })));
        records.AddRange(For(node).OutputDirectories.Select(p => "output:" + p));
        records.AddRange((For(node).OutputFiles ?? []).Order(StringComparer.Ordinal).Select(p => "output-file:" + p));
        records.Add("referenceBoundary:" + For(node).ReferenceBoundary);
        records.AddRange((For(node).DependencyCopies ?? []).OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => "copy:" + p.Key + "=" + p.Value));
        records.AddRange((For(node).ImplementationDependencies ?? []).Order(StringComparer.Ordinal).Select(path => "implementation:" + path));
        var compileInputs = project.GetItems("Compile").Select(item => Path.GetFullPath(item.EvaluatedInclude.Replace('\\', '/'), Path.GetDirectoryName(project.FullPath)!)).ToHashSet(StringComparer.Ordinal);
        // A source also consumed as content or analyzer data is not a compiler-only input.
        compileInputs.ExceptWith(new[] { "EmbeddedResource", "Content", "None", "AdditionalFiles", "Analyzer", "EditorConfigFiles", "GlobalAnalyzerConfigFiles", "RazorGenerate" }
            .SelectMany(project.GetItems).Select(item => Path.GetFullPath(item.EvaluatedInclude.Replace('\\', '/'), Path.GetDirectoryName(project.FullPath)!)));
        var paths = For(node).Inputs.Distinct().Order(StringComparer.Ordinal)
            .Where(path => !sharedPaths.Contains(resolvedInputs[path])).ToArray();
        baseFingerprints[node] = ContractFiles.Hash(records.Concat(paths.Select(path => path + ":" + inputDigests[path])));
        dependencyFingerprints[node] = ContractFiles.Hash(records.Concat(paths
            .Where(path => !compileInputs.Contains(resolvedInputs[path])).Select(path => path + ":" + inputDigests[path])));
    }

    internal void VerifyUnchangedInputs()
    {
        // Writable inputs still need a fresh byte/path pass. Packages verified
        // before execution may only skip it while their mount remains read-only.
        GraphDirectories.Prepare(contract, Files, create: false);
        if (readOnlyPackages)
        {
            ReadOnlyPackageTree.RequireReadOnly(Path.Combine(Files.Root, ".nuget"));
        }
        var mutable = inputDigests.Where(pair => !readOnlyPackages || !ReadOnlyPackageTree.Contains(pair.Key)).ToArray();
        var currentPaths = Files.ResolveInputs(mutable.Select(pair => pair.Key));
        foreach (var (relative, digest) in mutable)
        {
            if (ContractFiles.InputDigest(currentPaths[relative]) != digest)
            {
                throw new InvalidDataException("Build modified a declared input: " + relative);
            }
        }
    }

    private void Validate(ProjectGraphNode node)
    {
        if (contract.Version < 3 && For(node).ImplementationDependencies?.Length > 0)
        {
            throw new InvalidDataException("Implementation dependencies require graph contract version 3");
        }
        foreach (var dependency in For(node).ImplementationDependencies ?? [])
        {
            Files.Resolve(dependency);
            if (!node.ProjectReferences.Any(reference => Relative(reference) == dependency))
            {
                throw new InvalidDataException("Implementation dependency must be a direct ProjectReference: " + dependency);
            }
        }
        var allowed = For(node).Inputs.Select(path => resolvedInputs[path]).ToHashSet(StringComparer.Ordinal);
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
        foreach (var kind in new[] { "Compile", "EmbeddedResource", "Content", "None", "AdditionalFiles", "Analyzer", "EditorConfigFiles", "GlobalAnalyzerConfigFiles", "RazorGenerate" })
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
        var signingKey = node.ProjectInstance.GetPropertyValue("AssemblyOriginatorKeyFile");
        if (signingKey.Length != 0)
        {
            var path = Path.GetFullPath(signingKey.Replace('\\', '/'), Path.GetDirectoryName(node.ProjectInstance.FullPath)!);
            if (!path.StartsWith(Files.Sdk + Path.DirectorySeparatorChar, StringComparison.Ordinal))
            {
                Require(path);
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
            if (!allowed.Contains(path) && !sharedPaths.Contains(path))
            {
                // Some SDK resolvers return Sdk/Sdk.props for archives containing
                // sdk/Sdk.props on case-insensitive filesystems. Require matching
                // bytes from the declared package; never accept a case-only match.
                if (File.Exists(path) && packagePathAliases.TryGetValue(path, out var aliases) &&
                    aliases.Any(alias => ContractFiles.Digest(alias) == ContractFiles.Digest(path)))
                {
                    return;
                }
                throw new InvalidDataException("Undeclared graph input for " + Relative(node) + ": " + Path.GetRelativePath(Files.Root, path));
            }
        }
    }

    private void ValidateOutputOwnership()
    {
        var directories = Graph.ProjectNodes.SelectMany(node => OutputDirectories(node).Select(path => (node, path))).ToArray();
        var files = Graph.ProjectNodes.SelectMany(node => DeclaredOutputFiles(node).Select(path => (node, path))).ToArray();
        var inputPaths = resolvedInputs.Values;
        foreach (var (node, path) in files)
        {
            if (files.Any(other => (other.node != node && path == other.path) || path.StartsWith(other.path + "/", StringComparison.Ordinal) || other.path.StartsWith(path + "/", StringComparison.Ordinal)) ||
                directories.Any(other => (other.node != node && path.StartsWith(other.path + "/", StringComparison.Ordinal)) || other.path == path || other.path.StartsWith(path + "/", StringComparison.Ordinal)))
            {
                throw new InvalidDataException("Overlapping output file ownership: " + path);
            }
            if (inputPaths.Any(input => input == path || input.StartsWith(path + "/", StringComparison.Ordinal)))
            {
                throw new InvalidDataException("Output file overlaps a declared input: " + path);
            }
        }
        foreach (var (node, path) in directories)
        {
            if (directories.Any(other => other.node != node && (path == other.path || path.StartsWith(other.path + "/", StringComparison.Ordinal) || other.path.StartsWith(path + "/", StringComparison.Ordinal))))
            {
                throw new InvalidDataException("Overlapping output directories: " + path);
            }
            if (inputPaths.Any(input => input.StartsWith(path + "/", StringComparison.Ordinal)))
            {
                throw new InvalidDataException("Output directory contains a declared input: " + path);
            }
        }
    }

    public void Dispose() => collection.Dispose();
}
