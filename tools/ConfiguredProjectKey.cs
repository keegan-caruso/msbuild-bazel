using System.Text.Json;
using Microsoft.Build.Execution;

namespace RulesMSBuild;

// Property values may contain every legacy separator. Keep record boundaries
// explicit and preserve the existing ordinal name/case and value semantics.
internal static class ConfiguredProjectKey
{
    internal const string Format = "configured-project-v2";

    internal static string Create(ProjectInstance project) => Create(project.FullPath, project.GlobalProperties);
    internal static string Create(BuildRequestData request) => Create(request.ProjectFullPath,
        request.GlobalProperties.Select(property => KeyValuePair.Create(property.Name, property.EvaluatedValue)));

    private static string Create(string project, IEnumerable<KeyValuePair<string, string>> properties)
    {
        var records = new List<string> { Format, project };
        foreach (var (name, value) in properties.OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            records.Add(name);
            records.Add(value);
        }
        return JsonSerializer.Serialize(records);
    }
}
