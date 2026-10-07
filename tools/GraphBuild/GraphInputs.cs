using Microsoft.Build.Definition;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Evaluation.Context;
using Microsoft.Build.Execution;
using Microsoft.Build.Graph;

namespace RulesMSBuild.GraphBuild;

internal sealed class GraphInputs : IDisposable
{
    private readonly ProjectCollection collection;
    private readonly bool ownsCollection;
    private readonly GraphEvaluationProfile? evaluationProfile;
    private readonly OutputOwnership<ProjectGraphNode> ownership;
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
    internal object? EvaluationProfile => evaluationProfile?.Report;

    internal GraphInputs(GraphContract contract, string root, string sdkRoot, bool restored = false, RestoredInputs? prepared = null, EvaluationSession? evaluation = null)
    {
        var timer = System.Diagnostics.Stopwatch.StartNew();
        this.contract = contract;
        Files = new(root, sdkRoot);
        Dictionary<string, string>? verifiedInputs = null;
        string? verifiedSdk = null;
        if (evaluation is not null)
        {
            var paths = Files.ResolveInputs(contract.SharedInputs.Concat(contract.Projects.Values.SelectMany(project => project.Inputs
                .Concat((project.Configurations ?? []).SelectMany(configuration => configuration.Inputs)))).Concat(contract.Restore?.Outputs ?? []));
            using (GraphProfile.Measure("evaluationIdentity"))
            {
                verifiedInputs = paths.ToDictionary(pair => pair.Key, pair => prepared?.Digests.GetValueOrDefault(pair.Key) ?? ContractFiles.InputDigest(pair.Value), StringComparer.Ordinal);
                verifiedSdk = prepared?.SdkDigest ?? ContractFiles.TreeDigest(sdkRoot, 4);
                evaluation.Prepare(contract, Files, verifiedSdk, verifiedInputs);
            }
        }
        string sdk;
        Dictionary<string, string> properties;
        EvaluationContext evaluationContext;
        using (GraphProfile.Measure("evaluationSetup"))
        {
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
            if (contract.Version is not (1 or 2 or 3 or 4 or 5 or 6 or 7 or 8 or 9 or 10) || contract.Projects.Count == 0)
            {
                throw new InvalidDataException("Expected graph contract version 1, 2, 3, 4, 5, 6, 7, 8, 9 or 10 with explicit project inputs and outputs");
            }
            sdk = Path.Combine(sdkRoot, "sdk", contract.SdkVersion);
            if (!Directory.Exists(sdk))
            {
                throw new InvalidDataException("Selected SDK is missing: " + contract.SdkVersion);
            }
            Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(sdk, "MSBuild.dll"));
            Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(sdk, "Sdks"));
            ownsCollection = evaluation is null;
            collection = evaluation?.Collection ?? new ProjectCollection();
            properties = new Dictionary<string, string>(contract.Properties, StringComparer.OrdinalIgnoreCase);
            if (properties.ContainsKey("PathMap") || properties.ContainsKey("UseSharedCompilation") || properties.ContainsKey("NetCoreSdkRoot") || properties.ContainsKey("DOTNET_HOST_PATH"))
            {
                throw new InvalidDataException("SDK host paths, PathMap and UseSharedCompilation are controlled by the graph runner");
            }
            properties["PathMap"] = Files.Root + "=/_/workspace," + Files.Sdk + "=/_/sdk";
            properties["UseSharedCompilation"] = "false";
            properties["NetCoreSdkRoot"] = sdk;
            evaluationContext = evaluation?.Context ?? EvaluationContext.Create(EvaluationContext.SharingPolicy.Shared);
            evaluationProfile = GraphProfile.Enabled && GraphProfile.EvaluationEnabled ? new GraphEvaluationProfile(Files) : null;
            if (evaluationProfile is not null)
            {
                collection.RegisterLogger(evaluationProfile);
            }
        }
        using (GraphProfile.Measure("projectEvaluation"))
        {
            Graph = new ProjectGraph((contract.Entries ?? [contract.Entry]).Select(entry => new ProjectGraphEntryPoint(Files.Resolve(entry), GraphEntryProperties.For(entry, properties, contract.EntryProperties ?? []))), collection,
                (path, globals, projects) =>
                {
                    Project project;
                    using (GraphProfile.Measure("projectLoad"))
                    {
                        var options = new ProjectOptions
                        {
                            GlobalProperties = globals,
                            ProjectCollection = projects,
                            // Graph builds do not need IDE-only items from inactive conditions.
                            LoadSettings = ProjectLoadSettings.DoNotEvaluateElementsWithFalseCondition |
                                (evaluationProfile is null ? ProjectLoadSettings.Default : ProjectLoadSettings.ProfileEvaluation),
                            EvaluationContext = evaluationContext
                        };
                        project = evaluation?.Load(path, globals, options) ?? Project.FromFile(path, options);
                    }
                    ProjectInstance instance;
                    using (GraphProfile.Measure("projectInstance"))
                    {
                        var evaluationId = project.LastEvaluationId;
                        instance = project.CreateProjectInstance();
                        if (project.LastEvaluationId != evaluationId || instance.EvaluationId != evaluationId)
                        {
                            throw new InvalidDataException("Retained project unexpectedly reevaluated: " + path);
                        }
                        // Out-of-process build nodes otherwise evaluate the same
                        // project again to reconstruct targets and task registrations.
                        // Transfer the full pristine instance from this graph pass.
                        instance.TranslateEntireState = true;
                    }
                    using (GraphProfile.Measure("importCapture"))
                    {
                        var paths = project.Imports.Select(import => import.ImportedProject.FullPath).Distinct().ToArray();
                        imports[Key(instance)] = paths;
                        evaluationProfile?.Project(paths);
                    }
                    return instance;
                });
        }
        if (evaluationProfile is not null)
        {
            // Flush evaluation events before publishing diagnostics. Build logging
            // is supplied separately by BuildParameters, not this collection logger.
            collection.UnregisterAllLoggers();
        }
        using (GraphProfile.Measure("configurationSelection"))
        {
            foreach (var node in Graph.ProjectNodes)
            {
                projects.Add(node, restored ? RestoreInputs(node, Select(node)) : Select(node));
            }
        }
        if (contract.EvaluationReuseInputs is not null)
        {
            if (contract.Version is not (9 or 10))
            {
                throw new InvalidDataException("Evaluation reuse inputs require graph contract version 9 or 10");
            }
            var compiler = Graph.ProjectNodes.SelectMany(node => node.ProjectInstance.GetItems("Compile")
                .Select(item => Path.GetRelativePath(Files.Root, Path.GetFullPath(item.EvaluatedInclude.Replace('\\', '/'), Path.GetDirectoryName(node.ProjectInstance.FullPath)!))))
                .ToHashSet(StringComparer.Ordinal);
            var other = Graph.ProjectNodes.SelectMany(node => new[] { "EmbeddedResource", "Content", "None", "AdditionalFiles", "Analyzer", "EditorConfigFiles", "GlobalAnalyzerConfigFiles", "RazorGenerate" }
                .SelectMany(node.ProjectInstance.GetItems).Select(item => Path.GetRelativePath(Files.Root, Path.GetFullPath(item.EvaluatedInclude.Replace('\\', '/'), Path.GetDirectoryName(node.ProjectInstance.FullPath)!))))
                .ToHashSet(StringComparer.Ordinal);
            if (contract.EvaluationReuseInputs!.Any(path => !compiler.Contains(path) || other.Contains(path)))
            {
                throw new InvalidDataException("Evaluation reuse inputs must occur only as reviewed Compile items");
            }
        }
        readOnlyPackages = prepared?.ReadOnlyPackages == true;
        using (GraphProfile.Measure("inputPathValidation"))
        {
            resolvedInputs = Files.ResolveInputs(contract.SharedInputs.Concat(projects.Values.SelectMany(p => p.Inputs)));
        }
        using (GraphProfile.Measure("nodeValidation"))
        {
            foreach (var node in Graph.ProjectNodes)
            {
                Validate(node);
            }
        }
        using (GraphProfile.Measure("outputOwnershipIndex"))
        {
            var outputPaths = Files.ResolveInputs(projects.Values.SelectMany(project => project.OutputDirectories.Concat(project.OutputFiles ?? [])));
            ownership = new(Files.Root,
                Graph.ProjectNodes.SelectMany(node => For(node).OutputDirectories.Select(path => (node, outputPaths[path]))),
                Graph.ProjectNodes.SelectMany(node => (For(node).OutputFiles ?? []).Select(path => (node, outputPaths[path]))),
                resolvedInputs.Values);
        }
        using (GraphProfile.Measure("outputOwnershipValidation"))
        {
            ownership.Validate();
        }
        EvaluationSeconds = timer.Elapsed.TotalSeconds;
        timer.Restart();
        using (GraphProfile.Measure("sdkHash"))
        {
            SdkDigest = verifiedSdk ?? prepared?.SdkDigest ?? ContractFiles.TreeDigest(sdkRoot);
        }
        runnerDigest = ContractFiles.Digest(typeof(GraphInputs).Assembly.Location);
        inputDigests = resolvedInputs.ToDictionary(pair => pair.Key, pair => verifiedInputs?.GetValueOrDefault(pair.Key) ?? prepared?.Digests.GetValueOrDefault(pair.Key) ?? ContractFiles.InputDigest(pair.Value), StringComparer.Ordinal);
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
        if (contract.Version is not (2 or 3 or 4 or 5 or 6 or 7 or 8 or 9 or 10) || project.OutputDirectories.Length != 0 || project.OutputFiles?.Length > 0 || project.ReferenceBoundary || project.DependencyCopies?.Count > 0 || project.ImplementationDependencies?.Length > 0 || project.CompilerReference is not null || project.CompilerReferences?.Count > 0 || project.CompilerReferencesComplete || project.ReplayOmissions?.Length > 0)
        {
            throw new InvalidDataException("Configured projects require version 2, 3, 4, 5, 6, 7, 8, 9 or 10 and configuration-owned outputs: " + Relative(node));
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
            selected.OutputDirectories, selected.ReferenceBoundary, selected.DependencyCopies, OutputFiles: selected.OutputFiles, ImplementationDependencies: selected.ImplementationDependencies, CompilerReference: selected.CompilerReference, CompilerReferences: selected.CompilerReferences, ReplayOmissions: selected.ReplayOmissions, CompilerReferencesComplete: selected.CompilerReferencesComplete);
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
    private IEnumerable<string> CompilerProducts(ProjectGraphNode node) =>
        new[] { "TargetPath", "TargetRefPath" }.Select(node.ProjectInstance.GetPropertyValue).Where(value => value.Length != 0)
            .Select(value => Path.GetFullPath(value.Replace('\\', '/'), Path.GetDirectoryName(node.ProjectInstance.FullPath)!))
            .Where(value => OutputDirectories(node).Any(directory => value.StartsWith(directory + Path.DirectorySeparatorChar, StringComparison.Ordinal)))
            .Concat(DeclaredOutputFiles(node));

    // A complete inventory is reviewed at sync and checked against the SDK's
    // resolved compiler inputs before publishing each newly built snapshot.
    internal void VerifyCompilerReferences(ProjectGraphNode node, ProjectInstance? state)
    {
        if (!For(node).CompilerReferencesComplete)
        {
            return;
        }
        using var timing = GraphProfile.Measure("compilerReferenceVerification");
        if (state is null)
        {
            throw new InvalidDataException("Missing post-build compiler state: " + Relative(node));
        }
        var selected = new HashSet<string>(StringComparer.Ordinal);
        var allowed = For(node).Inputs.Select(path => resolvedInputs[path]).ToHashSet(StringComparer.Ordinal);
        foreach (var item in state.GetItems("ReferencePathWithRefAssemblies"))
        {
            var path = Path.GetFullPath(item.EvaluatedInclude.Replace('\\', '/'), Path.GetDirectoryName(state.FullPath)!);
            if (OutputOwner(path) is not null)
            {
                selected.Add(path);
            }
            else if (!allowed.Contains(path) && !sharedPaths.Contains(path) && !path.StartsWith(Files.Sdk + Path.DirectorySeparatorChar, StringComparison.Ordinal))
            {
                throw new InvalidDataException("Undeclared compiler input: " + Relative(node) + " -> " + path);
            }
        }
        var declared = (For(node).CompilerReferences ?? []).Values.Select(Files.Resolve).ToHashSet(StringComparer.Ordinal);
        if (!selected.SetEquals(declared))
        {
            throw new InvalidDataException("Complete compiler references differ from SDK selection: " + Relative(node) +
                "; missing: " + string.Join(", ", selected.Except(declared).Order(StringComparer.Ordinal)) +
                "; unused: " + string.Join(", ", declared.Except(selected).Order(StringComparer.Ordinal)));
        }
    }

    internal bool OwnsOutput(ProjectGraphNode node, string path) => OutputOwner(path) == node;
    internal ProjectGraphNode? OutputOwner(string path) => ownership.Owner(path);
    internal static string Key(ProjectInstance project) => project.FullPath + "|" + string.Join(";", project.GlobalProperties
        .OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => p.Key + "=" + p.Value));

    internal string Fingerprint(ProjectGraphNode node) => baseFingerprints[node];

    internal string DependencyFingerprint(ProjectGraphNode node) => dependencyFingerprints[node];

    internal bool IsDeclaredPackageInput(string path) =>
        path.StartsWith(Path.Combine(Files.Root, ".nuget") + Path.DirectorySeparatorChar, StringComparison.Ordinal) && sharedPaths.Contains(path);

    private void ComputeFingerprints(ProjectGraphNode node)
    {
        var project = node.ProjectInstance;
        var records = new List<string> { "graph-input-v2", Files.Root, Files.Sdk, SdkDigest, runnerDigest, sharedDigest, Relative(node) };
        records.AddRange((contract.TemporaryDirectories ?? []).Order(StringComparer.Ordinal).Select(path => "temporary-directory:" + path));
        records.AddRange((contract.InputDirectories ?? []).Order(StringComparer.Ordinal).Select(path => "input-directory:" + path));
        records.AddRange(project.Properties.OrderBy(p => p.Name, StringComparer.Ordinal)
            .Select(p => p.Name + "=" + (p.Name.Equals("MSBuildAllProjects", StringComparison.OrdinalIgnoreCase)
                ? GraphImportState.FingerprintValue(project, imports[Key(project)], p.EvaluatedValue)
                : p.EvaluatedValue)));
        records.AddRange(project.Items.Select(item => System.Text.Json.JsonSerializer.Serialize(new
        {
            item.ItemType,
            item.EvaluatedInclude,
            metadata = item.Metadata.OrderBy(m => m.Name, StringComparer.Ordinal).Select(m => new { m.Name, m.EvaluatedValue }).ToArray(),
        })));
        records.AddRange(For(node).OutputDirectories.Select(p => "output:" + p));
        records.AddRange((For(node).OutputFiles ?? []).Order(StringComparer.Ordinal).Select(p => "output-file:" + p));
        records.AddRange((For(node).ReplayOmissions ?? []).Order(StringComparer.Ordinal).Select(p => "replay-omission:" + p));
        records.Add("referenceBoundary:" + For(node).ReferenceBoundary);
        records.Add("compilerReferencesComplete:" + For(node).CompilerReferencesComplete);
        if (For(node).CompilerReference is not null)
        {
            records.Add("compiler-reference:" + For(node).CompilerReference);
        }
        records.AddRange((For(node).DependencyCopies ?? []).OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => "copy:" + p.Key + "=" + p.Value));
        records.AddRange((For(node).ImplementationDependencies ?? []).Order(StringComparer.Ordinal).Select(path => "implementation:" + path));
        records.AddRange((For(node).CompilerReferences ?? []).OrderBy(binding => binding.Key, StringComparer.Ordinal).Select(binding => "compiler-reference-binding:" + binding.Key + "=" + binding.Value));
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
        if (For(node).CompilerReferencesComplete && (contract.Version < 10 || !For(node).ReferenceBoundary))
        {
            throw new InvalidDataException("Complete compiler references require graph contract version 10 and a reviewed reference boundary");
        }
        var compilerReference = For(node).CompilerReference;
        foreach (var (producer, artifact) in For(node).CompilerReferences ?? [])
        {
            if (contract.Version < 8 || !For(node).ReferenceBoundary)
            {
                throw new InvalidDataException("Consumer compiler references require graph contract version 8 and a reviewed reference boundary");
            }
            RulesMSBuild.GraphCompilerReferences.ValidateConsumer(node, Files.Resolve(producer), Files.Resolve(artifact), CompilerProducts);
        }
        if (compilerReference is not null)
        {
            if (contract.Version < 7)
            {
                throw new InvalidDataException("Compiler references require graph contract version 7");
            }
            RulesMSBuild.GraphCompilerReferences.Validate(node, Files.Resolve(compilerReference), CompilerProducts);
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

    public void Dispose()
    {
        if (ownsCollection)
        {
            collection.Dispose();
        }
    }
}
