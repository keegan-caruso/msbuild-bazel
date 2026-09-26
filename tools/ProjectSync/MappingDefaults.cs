using System.Text.Json;
using System.Text.Json.Nodes;

namespace RulesMSBuild.ProjectSync;

// Defaults share reviewed contracts; they never infer or approve new inputs.
internal static class MappingDefaults
{
    private static readonly HashSet<string> Dictionaries = new(StringComparer.OrdinalIgnoreCase)
    {
        "properties", "documents", "references", "projectReferences", "packageReferencePaths", "itemPaths", "layoutBindings", "inputItems", "exportTargets", "packages", "generatedDirectories", "frameworkOverrides"
    };

    internal static string Expand(string text)
    {
        using var document = JsonDocument.Parse(text);
        RejectDuplicates(document.RootElement, "mappings");
        var root = JsonNode.Parse(text) as JsonObject ?? throw new InvalidDataException("Expected an object for sync mappings");
        Members(root, "mappings");
        var defaultsNode = Member(root, "projectDefaults");
        if (root.Any(p => p.Key.Equals("projectDefaults", StringComparison.OrdinalIgnoreCase)) && defaultsNode is not JsonObject)
        {
            throw new InvalidDataException("projectDefaults must be an object");
        }
        var defaults = defaultsNode as JsonObject ?? new JsonObject();
        Binding(defaults, "projectDefaults");
        if (Member(root, "projects") is JsonObject projects)
        {
            foreach (var (project, node) in projects.ToArray())
            {
                var specific = node as JsonObject ?? throw new InvalidDataException("Expected a project mapping object: " + project);
                Binding(specific, project);
                var merged = (JsonObject)defaults.DeepClone();
                foreach (var (key, value) in specific)
                {
                    var existing = merged.Select(p => p.Key).FirstOrDefault(k => k.Equals(key, StringComparison.OrdinalIgnoreCase)) ?? key;
                    if (Dictionaries.Contains(key) && merged[existing] is JsonObject inherited && value is JsonObject overrides)
                    {
                        foreach (var (identity, replacement) in overrides)
                        {
                            // A document/reference binding replaces the whole record, so
                            // its old hash or role cannot silently survive a partial override.
                            inherited[identity] = replacement?.DeepClone();
                        }
                    }
                    else
                    {
                        merged[existing] = value?.DeepClone();
                    }
                }
                ExpandFrameworks(merged, project);
                projects[project] = merged;
            }
        }
        ExpandFrameworks(defaults, "projectDefaults");
        return root.ToJsonString();
    }

    private static void ExpandFrameworks(JsonObject binding, string path)
    {
        if (Member(binding, "frameworkOverrides") is not JsonObject overrides)
        {
            return;
        }
        foreach (var (framework, node) in overrides.ToArray())
        {
            var specific = node as JsonObject ?? throw new InvalidDataException("Expected a framework override object: " + path + "." + framework);
            Binding(specific, path + "." + framework);
            if (specific.Any(p => p.Key.Equals("frameworkOverrides", StringComparison.OrdinalIgnoreCase) || p.Key.Equals("targetFrameworks", StringComparison.OrdinalIgnoreCase)))
            {
                throw new InvalidDataException("Framework overrides cannot select or nest frameworks: " + path + "." + framework);
            }
            var merged = new JsonObject();
            foreach (var (key, value) in binding.Where(p => !p.Key.Equals("frameworkOverrides", StringComparison.OrdinalIgnoreCase)))
            {
                merged[key] = value?.DeepClone();
            }
            foreach (var (key, value) in specific)
            {
                var existing = merged.Select(p => p.Key).FirstOrDefault(k => k.Equals(key, StringComparison.OrdinalIgnoreCase)) ?? key;
                if (Dictionaries.Contains(key) && merged[existing] is JsonObject inherited && value is JsonObject replacements)
                {
                    foreach (var (identity, replacement) in replacements)
                    {
                        inherited[identity] = replacement?.DeepClone();
                    }
                }
                else
                {
                    merged[existing] = value?.DeepClone();
                }
            }
            overrides[framework] = merged;
        }
    }

    private static void Binding(JsonObject value, string path)
    {
        Members(value, path);
        foreach (var (name, node) in value)
        {
            if (node is null && !name.Equals("referencePack", StringComparison.OrdinalIgnoreCase) && !name.Equals("runtimeHost", StringComparison.OrdinalIgnoreCase) && !name.Equals("packageLock", StringComparison.OrdinalIgnoreCase) && !name.Equals("useAppHost", StringComparison.OrdinalIgnoreCase) && !name.Equals("transitiveCompileReferences", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Null mapping field: " + path + "." + name);
            }
            if (Dictionaries.Contains(name) && node is JsonObject entries)
            {
                if (name.Equals("properties", StringComparison.OrdinalIgnoreCase))
                {
                    Members(entries, path + "." + name);
                }
                foreach (var (identity, entry) in entries)
                {
                    if (entry is null)
                    {
                        throw new InvalidDataException("Null mapping entry: " + path + "." + name + "." + identity);
                    }
                    if (entry is JsonObject record)
                    {
                        Members(record, path + "." + name + "." + identity);
                    }
                }
            }
        }
    }

    private static JsonNode? Member(JsonObject value, string name) => value.FirstOrDefault(p => p.Key.Equals(name, StringComparison.OrdinalIgnoreCase)).Value;

    private static void Members(JsonObject value, string path)
    {
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var (name, _) in value)
        {
            if (!names.Add(name))
            {
                throw new InvalidDataException("Ambiguous mapping member: " + path + "." + name);
            }
        }
    }

    private static void RejectDuplicates(JsonElement value, string path)
    {
        if (value.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var property in value.EnumerateObject())
            {
                if (!names.Add(property.Name))
                {
                    throw new InvalidDataException("Duplicate mapping key: " + path + "." + property.Name);
                }
                RejectDuplicates(property.Value, path + "." + property.Name);
            }
        }
        else if (value.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in value.EnumerateArray())
            {
                RejectDuplicates(item, path + "[]");
            }
        }
    }
}
