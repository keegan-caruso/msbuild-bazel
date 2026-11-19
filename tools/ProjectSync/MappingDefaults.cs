using System.Text.Json;
using System.Text.Json.Nodes;

namespace RulesMSBuild.ProjectSync;

// Defaults share reviewed contracts; they never infer or approve new inputs.
internal static class MappingDefaults
{
    private static readonly HashSet<string> Dictionaries = new(StringComparer.OrdinalIgnoreCase)
    {
        "properties", "documents", "inputItems", "frameworkOverrides"
    };

    internal static string Expand(string text)
    {
        JsonObject root;
        try
        {
            root = JsonNode.Parse(text, documentOptions: new()
            {
                AllowDuplicateProperties = false
            }) as JsonObject
                ?? throw new InvalidDataException("Expected an object for sync mappings");
        }
        catch (JsonException error)
        {
            throw new InvalidDataException("Invalid sync mappings: " + error.Message, error);
        }
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
                var merged = Merge(defaults, specific);
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
            var merged = Merge(binding.Where(p => !p.Key.Equals("frameworkOverrides", StringComparison.OrdinalIgnoreCase)), specific);
            overrides[framework] = merged;
        }
    }

    private static JsonObject Merge(IEnumerable<KeyValuePair<string, JsonNode?>> inherited, JsonObject specific)
    {
        var merged = new JsonObject(inherited.Select(pair => KeyValuePair.Create(pair.Key, pair.Value?.DeepClone())));
        foreach (var (key, value) in specific)
        {
            var existing = merged.Select(pair => pair.Key).FirstOrDefault(name => name.Equals(key, StringComparison.OrdinalIgnoreCase)) ?? key;
            if (Dictionaries.Contains(key) && merged[existing] is JsonObject entries && value is JsonObject replacements)
            {
                foreach (var (identity, replacement) in replacements)
                {
                    // Replace whole records: a partial document override must
                    // never retain the inherited hash or target/task contract.
                    entries[identity] = replacement?.DeepClone();
                }
            }
            else
            {
                merged[existing] = value?.DeepClone();
            }
        }
        return merged;
    }

    private static void Binding(JsonObject value, string path)
    {
        Members(value, path);
        foreach (var (name, node) in value)
        {
            if (node is null && !name.Equals("referenceBoundary", StringComparison.OrdinalIgnoreCase) && !name.Equals("compilerReference", StringComparison.OrdinalIgnoreCase))
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
}
