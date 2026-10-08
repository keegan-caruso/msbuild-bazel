using System.Security.Cryptography;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Execution;
using Microsoft.Build.Graph;

namespace RulesMSBuild.ProjectSync;

internal sealed record ResolvedGraphInputs(Dictionary<string, string> CompilerReferences, Dictionary<string, string> DependencyCopies)
{
    // Evaluation cannot predict reference selection performed by SDK/custom targets.
    // Qualify once in the private offline workspace; ordinary builds use the contract.
    internal static Dictionary<ProjectGraphNode, ResolvedGraphInputs> Build(ProjectGraph graph, ProjectCollection collection,
        string root, string sdkRoot, ProjectGraphNode[] selected, Func<ProjectGraphNode, IEnumerable<string>> products,
        Func<ProjectGraphNode, IEnumerable<ProjectGraphNode>> dependencies, IEnumerable<string> inputs, HashSet<string> packages,
        Func<ProjectGraphNode, IEnumerable<string>> consumerInputs)
    {
        if (selected.Length == 0)
        {
            throw new InvalidDataException("Compiler input resolution requires at least one supported reference boundary");
        }
        foreach (var project in graph.ProjectNodes.Select(node => node.ProjectInstance))
        {
            foreach (var name in new[] { "OutputPath", "IntermediateOutputPath", "TargetPath", "PublishDir" })
            {
                var value = project.GetPropertyValue(name);
                if (value.Length != 0)
                {
                    WorkspaceView.Safe(Path.GetRelativePath(root, Path.TrimEndingDirectorySeparator(Full(project, value))).Replace('\\', '/'));
                }
            }
        }
        var declared = inputs.ToHashSet(StringComparer.Ordinal);
        var digests = declared.ToDictionary(path => path, path => Digest(Path.Combine(root, path)), StringComparer.Ordinal);
        var oldDirectory = Directory.GetCurrentDirectory();
        var oldPackages = Environment.GetEnvironmentVariable("NUGET_PACKAGES");
        GraphBuildResult result;
        try
        {
            Directory.SetCurrentDirectory(root);
            Environment.SetEnvironmentVariable("NUGET_PACKAGES", Path.Combine(root, ".nuget"));
            using var manager = new BuildManager();
            result = manager.Build(new BuildParameters(collection)
            {
                MaxNodeCount = 1,
                EnableNodeReuse = false,
                Loggers = [new Microsoft.Build.Logging.ConsoleLogger(Microsoft.Build.Framework.LoggerVerbosity.Minimal)]
            }, new GraphBuildRequestData(graph, ["Build"], null, BuildRequestDataFlags.ProvideProjectStateAfterBuild));
        }
        finally
        {
            Directory.SetCurrentDirectory(oldDirectory);
            Environment.SetEnvironmentVariable("NUGET_PACKAGES", oldPackages);
        }
        if (result.OverallResult != BuildResultCode.Success)
        {
            throw new InvalidDataException("Compiler input qualification Build failed: " + result.Exception);
        }
        foreach (var (path, digest) in digests)
        {
            if (!File.Exists(Path.Combine(root, path)) || Digest(Path.Combine(root, path)) != digest)
            {
                throw new InvalidDataException("Qualification Build modified a declared input: " + path);
            }
        }
        var owners = graph.ProjectNodes.Where(node => GraphProjectKind.HasAssembly(node.ProjectInstance))
            .SelectMany(node => products(node).Where(path => Path.GetExtension(path) == ".dll").Select(path => (path, node)))
            .GroupBy(pair => pair.path, StringComparer.Ordinal).ToDictionary(group => group.Key,
                group => group.Select(pair => pair.node).Distinct().ToArray(), StringComparer.Ordinal);
        var selections = new Dictionary<ProjectGraphNode, ResolvedGraphInputs>();
        foreach (var node in selected)
        {
            var state = result.ResultsByNode.GetValueOrDefault(node)?.ProjectStateAfterBuild
                ?? throw new InvalidDataException("Missing resolved compiler state: " + Relative(node.ProjectInstance.FullPath));
            var closure = dependencies(node).ToHashSet();
            var allowed = consumerInputs(node).ToHashSet(StringComparer.Ordinal);
            var references = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var item in state.GetItems("ReferencePathWithRefAssemblies"))
            {
                var path = Full(state, item.EvaluatedInclude);
                var owner = Owner(path, closure);
                if (owner is not null)
                {
                    var producer = Relative(owner.ProjectInstance.FullPath);
                    var artifact = Relative(path);
                    if (references.TryGetValue(producer, out var previous) && previous != artifact)
                    {
                        throw new InvalidDataException("Ambiguous configured compiler producer: " + producer);
                    }
                    references[producer] = artifact;
                }
                else if (!IsSdk(path) && !IsPackage(path) && !allowed.Contains(Relative(path)))
                {
                    throw new InvalidDataException("Undeclared resolved compiler input: " + path);
                }
            }
            var copies = new Dictionary<string, string>(StringComparer.Ordinal);
            var target = Full(state, state.GetPropertyValue("TargetPath"));
            var output = Path.GetDirectoryName(target)!;
            var publish = state.GetPropertyValue("PublishDir");
            var destinations = publish.Length == 0 ? [output] : new[] { output, Full(state, publish) }.Distinct().ToArray();
            foreach (var item in state.GetItems("ReferenceCopyLocalPaths"))
            {
                var path = Full(state, item.EvaluatedInclude);
                if (Path.GetExtension(path) is not (".dll" or ".pdb" or ".xml"))
                {
                    continue;
                }
                if (!IsDependencyOutput(path, closure) && !IsPackage(path))
                {
                    if (!IsSdk(path))
                    {
                        throw new InvalidDataException("Unowned resolved dependency copy: " + path);
                    }
                    continue; // SDK copies retain SDK input hashes and fixed snapshot payloads.
                }
                var subdirectory = item.GetMetadataValue("DestinationSubDirectory").Replace('\\', '/');
                if (subdirectory.Length != 0)
                {
                    WorkspaceView.Safe(subdirectory.TrimEnd('/'));
                }
                foreach (var extension in new[] { Path.GetExtension(path), ".pdb", ".xml" }.Distinct())
                {
                    var source = Path.ChangeExtension(path, extension);
                    var copied = Path.Combine(output, subdirectory, Path.GetFileName(source));
                    if (!File.Exists(source) || !File.Exists(copied))
                    {
                        continue;
                    }
                    if (Path.ChangeExtension(copied, ".dll") == target || Digest(source) != Digest(copied))
                    {
                        throw new InvalidDataException("Resolved dependency copy conflicts with consumer output: " + copied);
                    }
                    foreach (var destination in destinations)
                    {
                        var relative = Relative(Path.Combine(destination, subdirectory, Path.GetFileName(source)));
                        if (copies.TryGetValue(relative, out var previous) && previous != Relative(source))
                        {
                            throw new InvalidDataException("Ambiguous resolved dependency copy: " + relative);
                        }
                        copies[relative] = Relative(source);
                    }
                }
            }
            selections.Add(node, new(references, copies));
        }
        return selections;

        string Relative(string path) => WorkspaceView.Safe(Path.GetRelativePath(root, path).Replace('\\', '/'));
        bool IsSdk(string path) => path.StartsWith(sdkRoot + Path.DirectorySeparatorChar, StringComparison.Ordinal);
        bool IsPackage(string path)
        {
            if (!path.StartsWith(Path.Combine(root, ".nuget") + Path.DirectorySeparatorChar, StringComparison.Ordinal))
            {
                return false;
            }
            var parts = Relative(path).Split('/');
            return parts.Length >= 4 && packages.Contains(parts[1] + "/" + parts[2]);
        }
        ProjectGraphNode? Owner(string path, HashSet<ProjectGraphNode> closure)
        {
            if (!owners.TryGetValue(path, out var candidates))
            {
                return null;
            }
            var matches = candidates.Where(closure.Contains).ToArray();
            if (matches.Length != 1)
            {
                throw new InvalidDataException("Ambiguous or unrelated resolved project product: " + path);
            }
            return matches[0];
        }
        bool IsDependencyOutput(string path, HashSet<ProjectGraphNode> closure)
        {
            // Transitive copy items may name an already composed dependency
            // layout (B/bin/C.dll), rather than C's original TargetPath.
            var owners = closure.Where(node => GraphProjectKind.HasAssembly(node.ProjectInstance) || GraphProjectKind.IsNoTargets(node.ProjectInstance))
                .Where(node => products(node).Contains(path, StringComparer.Ordinal) ||
                new[] { "OutputPath", "IntermediateOutputPath" }.Select(node.ProjectInstance.GetPropertyValue)
                    .Where(value => value.Length != 0).Any(value => path.StartsWith(
                        Path.TrimEndingDirectorySeparator(Full(node.ProjectInstance, value)) + Path.DirectorySeparatorChar,
                        StringComparison.Ordinal))).ToArray();
            if (owners.Length > 1)
            {
                throw new InvalidDataException("Ambiguous resolved dependency output: " + path);
            }
            return owners.Length == 1;
        }
    }

    private static string Full(ProjectInstance project, string value) =>
        Path.GetFullPath(value.Replace('\\', '/'), Path.GetDirectoryName(project.FullPath)!);

    private static string Digest(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }
}
