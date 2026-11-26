using System.Text.Json;
using Microsoft.Build.Execution;
using Microsoft.Build.Graph;

namespace RulesMSBuild.GraphBuild;

// A fresh SDK design-time request exports state, rather than caching compiler
// results that contain no assembly bytes. Paths belong to the staged workspace.
internal static class DesignTimeBuild
{
    internal static GraphContract Configure(GraphContract contract)
    {
        var properties = new Dictionary<string, string>(contract.Properties, StringComparer.OrdinalIgnoreCase)
        {
            ["DesignTimeBuild"] = "true",
            ["SkipCompilerExecution"] = "true",
            ["ProvideCommandLineArgs"] = "true",
            ["BuildProjectReferences"] = "false",
        };
        return contract with
        {
            Properties = properties
        };
    }

    internal static int Run(GraphInputs inputs, string root, string report)
    {
        if (inputs.Graph.ProjectNodes.Any(node => node.ProjectInstance.GetPropertyValue("Language") != "C#" ||
            node.ProjectInstance.GetPropertyValue("IsCrossTargetingBuild").Equals("true", StringComparison.OrdinalIgnoreCase)))
        {
            throw new InvalidDataException("DesignTimeBuild currently qualifies single-framework C# SDK projects only");
        }
        foreach (var node in inputs.Graph.ProjectNodes)
        {
            var state = node.ProjectInstance;
            if (new[] { "DesignTimeBuild", "SkipCompilerExecution", "ProvideCommandLineArgs" }.Any(name =>
                !state.GetPropertyValue(name).Equals("true", StringComparison.OrdinalIgnoreCase)) ||
                !state.GetPropertyValue("BuildProjectReferences").Equals("false", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("DesignTimeBuild properties cannot be overridden by entry properties");
            }
        }
        // Compile does not schedule referenced projects itself. Make each
        // configured node an entry point so every editor project has state.
        // Preserve validated inputs and bounded SDK analyzer-config discovery.
        var instances = inputs.Graph.ProjectNodes.ToDictionary(node => ConfiguredProjectKey.Create(node.ProjectInstance),
            node => node.ProjectInstance, StringComparer.Ordinal);
        var graph = new ProjectGraph(inputs.Graph.ProjectNodes.Select(node =>
            new ProjectGraphEntryPoint(node.ProjectInstance.FullPath, node.ProjectInstance.GlobalProperties)), inputs.Collection, (path, globals, _) =>
                instances.GetValueOrDefault(ConfiguredProjectKey.Create(path, globals)) ??
                throw new InvalidDataException("Unexpected design-time project configuration: " + path));
        using var manager = new BuildManager();
        var result = manager.Build(new BuildParameters(inputs.Collection)
        {
            EnableNodeReuse = false,
            Loggers = [new Microsoft.Build.Logging.ConsoleLogger(Microsoft.Build.Framework.LoggerVerbosity.Minimal)],
        }, new GraphBuildRequestData(graph, ["Compile"], null, BuildRequestDataFlags.ProvideProjectStateAfterBuild));
        if (result.OverallResult != BuildResultCode.Success)
        {
            return 1;
        }
        inputs.VerifyUnchangedInputs();
        var sdk = Environment.GetEnvironmentVariable("DOTNET_ROOT")!;
        string Normalize(string value) => value.Replace(root, "{workspace}", StringComparison.Ordinal)
            .Replace(sdk, "{sdk}", StringComparison.Ordinal);
        var projects = graph.ProjectNodes.OrderBy(inputs.Relative, StringComparer.Ordinal).Select(node =>
        {
            var state = result.ResultsByNode.TryGetValue(node, out var build) ? build.ProjectStateAfterBuild : null;
            if (state is null)
            {
                throw new InvalidDataException("Missing design-time project state: " + inputs.Relative(node));
            }
            string[] Items(string name) => state.GetItems(name).Select(item => Normalize(item.EvaluatedInclude)).ToArray();
            return new
            {
                project = inputs.Relative(node),
                properties = node.ProjectInstance.GlobalProperties.ToDictionary(pair => pair.Key, pair => Normalize(pair.Value)),
                targetPath = Normalize(state.GetPropertyValue("TargetPath")),
                targetRefPath = Normalize(state.GetPropertyValue("TargetRefPath")),
                compile = Items("Compile"),
                references = Items("ReferencePath"),
                projectReferences = state.GetItems("ProjectReference").Select(item =>
                    RelativePathComponents.LogicalRelative(root, item.GetMetadataValue("FullPath")).Replace('\\', '/')).Distinct().Order(StringComparer.Ordinal).ToArray(),
                defineConstants = state.GetPropertyValue("DefineConstants"),
                compilerArguments = Items("CscCommandLineArgs"),
            };
        }).ToArray();
        File.WriteAllText(report, JsonSerializer.Serialize(new
        {
            version = 1,
            designTimeBuild = true,
            pathRoots = new[] { "{workspace}", "{sdk}" },
            projects,
        }, new JsonSerializerOptions { WriteIndented = true }));
        return 0;
    }
}
