using System.Text.Json.Serialization;
using Microsoft.Build.Graph;

namespace RulesMSBuild.ProjectSync;

internal sealed record GraphRestoreDeclaration(string[] Inputs, string[] Outputs,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string[]? BuildInputs = null, [property: JsonIgnore] bool Inferred = false);

internal static class GraphRestoreGenerator
{
    internal static GraphRestoreDeclaration? Create(ProjectGraph graph, GraphMappings mappings, IEnumerable<string> definitions,
        IEnumerable<string> shared, Func<string, string> relative, string[] buildInputs, bool hasBuildInputs, bool closed = false, IEnumerable<string>? conservativeInputs = null, bool standardDocuments = false)
    {
        var nodes = graph.ProjectNodes.Select(node => (node, binding: mappings.ForProject(relative(node.ProjectInstance.FullPath),
            node.ProjectInstance.GetPropertyValue("TargetFramework")))).ToArray();
        // Infer only bundled standard SDK Restore with no authored hooks or
        // package tasks. Reviewed custom workflows retain their explicit contract.
        var inferred = closed && standardDocuments && nodes.Any(pair => pair.binding.PreparedRestore is null) && nodes.All(pair => pair.binding.PreparedRestore != false &&
            pair.binding.Documents.Count == 0 && pair.binding.InputItems.Count == 0 && pair.binding.CompileGlobs.Length == 0 &&
            pair.binding.OutputFiles.Length == 0 && pair.binding.InputDirectories.Length == 0 &&
            pair.node.ProjectInstance.GetItems("PackageReference").Count == 0 &&
            System.Xml.Linq.XDocument.Load(pair.node.ProjectInstance.FullPath).Root?.Attribute("Sdk")?.Value == "Microsoft.NET.Sdk");
        bool Prepared((ProjectGraphNode node, ProjectBinding binding) pair) => pair.binding.PreparedRestore ?? inferred;
        if (!nodes.Any(Prepared))
        {
            if (hasBuildInputs)
            {
                throw new InvalidDataException("build_inputs requires preparedRestore for every configuration");
            }
            return null;
        }
        if (nodes.Any(pair => !Prepared(pair)))
        {
            throw new InvalidDataException("Prepared graph Restore requires a complete contract for every configuration");
        }
        var required = definitions.Concat(nodes.SelectMany(pair => pair.binding.RestoreInputs)).ToArray();
        if (required.Intersect(buildInputs, StringComparer.Ordinal).Any())
        {
            throw new InvalidDataException("Build-only producer content cannot be a definition or explicit Restore input");
        }
        var outputs = nodes.SelectMany(pair =>
        {
            var project = pair.node.ProjectInstance;
            var assets = project.GetPropertyValue("ProjectAssetsFile");
            var extensions = project.GetPropertyValue("MSBuildProjectExtensionsPath");
            if (assets.Length == 0 || extensions.Length == 0)
            {
                throw new InvalidDataException("Prepared graph Restore requires explicit SDK asset paths: " + project.FullPath);
            }
            var directory = Path.GetDirectoryName(project.FullPath)!;
            var extensionRoot = Path.GetFullPath(extensions, directory);
            return new[]
            {
                relative(Path.GetFullPath(assets, directory)),
                relative(Path.Combine(extensionRoot, Path.GetFileName(project.FullPath) + ".nuget.g.props")),
                relative(Path.Combine(extensionRoot, Path.GetFileName(project.FullPath) + ".nuget.g.targets")),
                relative(Path.Combine(extensionRoot, Path.GetFileName(project.FullPath) + ".nuget.dgspec.json")),
                relative(Path.Combine(extensionRoot, "project.nuget.cache"))
            // Build can consume a shared ProjectAssetsFile while NuGet still
            // writes this project's own assets during the private Restore.
            }.Concat(File.Exists(Path.Combine(extensionRoot, "project.assets.json"))
                ? new[] { relative(Path.Combine(extensionRoot, "project.assets.json")) } : [])
                .Concat(pair.binding.RestoreOutputs.Select(WorkspaceView.Safe));
        }).Distinct().Order(StringComparer.Ordinal).ToArray();
        var inputs = required.Concat(shared.Except(buildInputs, StringComparer.Ordinal))
            .Concat(inferred ? (conservativeInputs ?? []).Except(outputs, StringComparer.Ordinal).Except(buildInputs, StringComparer.Ordinal) : [])
            .Select(WorkspaceView.Safe).Distinct().Order(StringComparer.Ordinal).ToArray();
        if (outputs.Any(path => inputs.Contains(path) || buildInputs.Contains(path)))
        {
            throw new InvalidDataException("Prepared graph Restore outputs overlap authored inputs");
        }
        return new(inputs, outputs, hasBuildInputs ? buildInputs : null, inferred);
    }
}
