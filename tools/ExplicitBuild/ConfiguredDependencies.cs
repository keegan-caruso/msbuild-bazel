using Microsoft.Build.Execution;

internal static class ConfiguredDependencies
{
    internal static void ValidateProducer(Request request, ProjectInstance evaluated)
    {
        var expected = new Dictionary<string, string>(request.Properties, StringComparer.OrdinalIgnoreCase)
        {
            ["Configuration"] = request.Configuration,
            ["TargetFramework"] = request.Framework,
        };
        foreach (var (name, value) in expected)
        {
            if (evaluated.GetPropertyValue(name) != value)
            {
                throw new InvalidDataException("Explicit producer property was overridden: " + name);
            }
        }
    }
    internal static void Validate(Request request, ProjectItemInstance edge, string project, ProjectInstance evaluated)
    {
        foreach (var name in edge.GetMetadataValue("GlobalPropertiesToRemove").Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (!evaluated.GlobalProperties.ContainsKey(name))
            {
                continue;
            }

            if (!request.Properties.Keys.Contains(name, StringComparer.OrdinalIgnoreCase) || request.DependencyProperties is null || !request.DependencyProperties.TryGetValue(project, out var selected) || selected.Keys.Contains(name, StringComparer.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Configured ProjectReference removal disagrees with Bazel producer: " + project + " " + name);
            }
        }
        foreach (var metadata in new[] { "SetConfiguration", "SetTargetFramework", "AdditionalProperties" })
        {
            var text = edge.GetMetadataValue(metadata);
            if (text.Length == 0)
            {
                continue;
            }

            if (request.DependencyProperties is null || !request.DependencyProperties.TryGetValue(project, out var declared))
            {
                throw new InvalidDataException("Configured ProjectReference requires a declared configured dependency: " + project);
            }

            var properties = new Dictionary<string, string>(declared, StringComparer.OrdinalIgnoreCase);
            foreach (var assignment in text.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            {
                var separator = assignment.IndexOf('=');
                if (separator <= 0 || !properties.TryGetValue(assignment[..separator], out var actual) || actual != assignment[(separator + 1)..])
                {
                    throw new InvalidDataException("Configured ProjectReference disagrees with Bazel producer: " + project + " " + assignment);
                }
            }
        }
    }
}
