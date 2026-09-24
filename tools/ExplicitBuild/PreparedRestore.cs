using System.Text.Json;
using System.Text.Json.Nodes;
using System.Xml.Linq;

// Qualified shared restore slice: plain, package-free Microsoft.NET.Sdk projects.
// Unknown project behavior fails closed; ordinary per-project restore remains available.
internal static class PreparedRestore
{
    private sealed record Artifact(int Version, string Framework, string Configuration, bool Executable, string SdkVersion, Dictionary<string, string> Files);
    private static readonly HashSet<string> Properties = new(StringComparer.Ordinal)
    {
        "TargetFramework", "Configuration", "AssemblyName", "OutputType", "Nullable", "LangVersion", "AllowUnsafeBlocks", "DefineConstants",
    };
    internal static void Validate(Request r, string original)
    {
        void Reject() => throw new InvalidDataException("Shared restore requires a plain package-free Microsoft.NET.Sdk project; use per-project restore for custom restore behavior");
        if (r.Packages.Length != 0 || r.Imports.Length != 0 || r.AdapterImports is { Length: > 0 } || r.FrameworkReferences.Length != 0 || r.Properties.Keys.Any(k => !Properties.Contains(k)))
        {
            Reject();
        }

        if (r.Sources.Concat(r.Items.Select(i => i.File)).Any(f => Path.GetFileName(f.Path) is "Directory.Build.props" or "Directory.Build.targets" or "Directory.Packages.props" or "global.json"))
        {
            Reject();
        }

        var root = XDocument.Load(original).Root!;
        if (root.Name != "Project" || (string?)root.Attribute("Sdk") != "Microsoft.NET.Sdk" || root.Attributes().Count() != 1)
        {
            Reject();
        }

        foreach (var group in root.Elements())
        {
            if (group.HasAttributes || group.Name != "PropertyGroup" && group.Name != "ItemGroup")
            {
                Reject();
            }

            foreach (var item in group.Elements())
            {
                if (group.Name == "PropertyGroup")
                {
                    if (!Properties.Contains(item.Name.LocalName) || item.Name.NamespaceName.Length != 0 || item.HasAttributes || item.HasElements || item.Value.Contains('$') || item.Value.Contains('@'))
                    {
                        Reject();
                    }
                }
                else if (item.Name != "ProjectReference" && item.Name != "Compile" && item.Name != "EmbeddedResource" && item.Name != "None" && item.Name != "Content")
                {
                    Reject();
                }
            }
        }
    }
    private static Dictionary<string, string> Paths(Session s) => new()
    {
        ["__BAZEL_RESTORE_PROJECT__"] = Path.Combine(s.Workspace, s.Request.Project.Path),
        ["__BAZEL_RESTORE_PROJECT_NAME__"] = Path.GetFileNameWithoutExtension(s.Request.Project.Path),
        ["__BAZEL_RESTORE_STATE__"] = s.State,
        ["__BAZEL_RESTORE_WORKSPACE__"] = s.Workspace,
        ["__BAZEL_RESTORE_SDK__"] = s.Sdk,
    };
    private static string Rebase(string contents, string name, IEnumerable<KeyValuePair<string, string>> replacements)
    {
        string Replace(string value)
        {
            foreach (var (from, to) in replacements)
            {
                value = value.Replace(from, to, StringComparison.Ordinal);
            }

            return value;
        }
        JsonNode? Map(JsonNode? node) => node switch
        {
            JsonObject obj => new JsonObject(obj.Select(p => KeyValuePair.Create(Replace(p.Key), Map(p.Value)))),
            JsonArray array => new JsonArray(array.Select(Map).ToArray()),
            JsonValue value when value.TryGetValue<string>(out var text) => JsonValue.Create(Replace(text)),
            _ => node?.DeepClone(),
        };
        if (name.EndsWith(".json", StringComparison.Ordinal))
        {
            return Map(JsonNode.Parse(contents))!.ToJsonString(Program.Json);
        }

        var xml = XDocument.Parse(contents);
        foreach (var attribute in xml.Descendants().Attributes())
        {
            attribute.Value = Replace(attribute.Value);
        }

        foreach (var text in xml.DescendantNodes().OfType<XText>())
        {
            text.Value = Replace(text.Value);
        }

        return xml.ToString();
    }
    internal static void Export(Session s)
    {
        var files = new Dictionary<string, string>();
        var project = Path.GetFileName(s.Request.Project.Path);
        foreach (var name in new[] { "project.assets.json", project + ".nuget.g.props", project + ".nuget.g.targets" })
        {
            var contents = File.ReadAllText(Path.Combine(s.State, "obj", name));
            contents = Rebase(contents, name, Paths(s).Select(p => KeyValuePair.Create(p.Value, p.Key)));
            files.Add(name.Replace(project, "project", StringComparison.Ordinal), contents);
        }
        var r = s.Request;
        File.WriteAllText(Path.Combine(s.State, "restore.json"), JsonSerializer.Serialize(new Artifact(1, r.Framework, r.Configuration, r.Executable, r.SdkVersion, files), Program.Json));
    }
    internal static void Install(Session s, Func<string, string>? compilerPath = null)
    {
        var r = s.Request;
        var artifact = JsonSerializer.Deserialize<Artifact>(File.ReadAllText(r.RestoreInput!), Program.Json)!;
        if (artifact.Version != 1 || artifact.Framework != r.Framework || artifact.Configuration != r.Configuration || artifact.Executable != r.Executable || artifact.SdkVersion != r.SdkVersion)
        {
            throw new InvalidDataException("Shared restore identity mismatch");
        }

        var names = new[] { "project.assets.json", "project.nuget.g.props", "project.nuget.g.targets" };
        if (!names.ToHashSet(StringComparer.Ordinal).SetEquals(artifact.Files.Keys))
        {
            throw new InvalidDataException("Invalid shared restore files");
        }

        Directory.CreateDirectory(Path.Combine(s.State, "obj"));
        foreach (var (name, contents) in artifact.Files)
        {
            var value = Rebase(contents, name, Paths(s).Select(p => KeyValuePair.Create(p.Key, compilerPath is null ? p.Value : compilerPath(p.Value))));
            var destination = name == "project.assets.json" ? name : Path.GetFileName(r.Project.Path) + name["project".Length..];
            File.WriteAllText(Path.Combine(s.State, "obj", destination), value);
        }
    }
}
