namespace RulesMSBuild;

// Root overrides are explicit global properties, not inferred project settings.
// Restore drops TargetFramework only, retaining the authored package closure.
internal static class GraphEntryProperties
{
    internal static void Validate(IEnumerable<string> entries, Dictionary<string, Dictionary<string, string>> overrides, IEnumerable<string> tools)
    {
        var roots = entries.ToHashSet(StringComparer.Ordinal);
        var toolNames = tools.ToHashSet(StringComparer.OrdinalIgnoreCase);
        foreach (var (entry, values) in overrides)
        {
            if (!roots.Contains(entry) || values is null)
            {
                throw new InvalidDataException("Entry properties require a selected graph root: " + entry);
            }
            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var (name, value) in values)
            {
                System.Xml.XmlConvert.VerifyNCName(name);
                if (!names.Add(name) || value is null || toolNames.Contains(name) ||
                    name.StartsWith("MSBuild", StringComparison.OrdinalIgnoreCase) || name.StartsWith("Restore", StringComparison.OrdinalIgnoreCase) ||
                    name.StartsWith("_Bazel", StringComparison.OrdinalIgnoreCase) || name.Equals("PathMap", StringComparison.OrdinalIgnoreCase) ||
                    name.Equals("UseSharedCompilation", StringComparison.OrdinalIgnoreCase) || name.Equals("NetCoreSdkRoot", StringComparison.OrdinalIgnoreCase) ||
                    name.Equals("DOTNET_HOST_PATH", StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidDataException("Reserved, ambiguous or conflicting graph entry property: " + name);
                }
            }
        }
    }

    internal static Dictionary<string, string> For(string entry, Dictionary<string, string> defaults, Dictionary<string, Dictionary<string, string>> overrides)
    {
        var properties = new Dictionary<string, string>(defaults, StringComparer.OrdinalIgnoreCase);
        foreach (var (name, value) in overrides.GetValueOrDefault(entry) ?? [])
        {
            properties[name] = value;
        }
        return properties;
    }
}
