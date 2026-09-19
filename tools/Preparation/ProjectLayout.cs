using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

// Portable analysis declarations, generated from qualified MSBuild evaluation.
// Discovery remains the authority and verifies this entire layout in one action.
internal static class ProjectLayout
{
    public static JsonNode Capture(JsonNode graph)
    {
        var nodes = NativePlan.Qualify(graph); var projects = new JsonObject();
        var graphInputs = graph["graphInputs"] as JsonArray ?? [];
        IEnumerable<string> Structural(JsonNode node)
        {
            var visited = new HashSet<string>(StringComparer.Ordinal);
            var inputs = new HashSet<string>(StringComparer.Ordinal);
            void Add(JsonNode current)
            {
                if (!visited.Add(current.String("id"))) return;
                foreach (var input in current.Array("inputs").Concat(graphInputs))
                    if (!NativePlan.SourceBody(input!) && input!.String("path").StartsWith("workspace/", StringComparison.Ordinal))
                    {
                        var path = Host.Relative(input.String("path"));
                        if (!path.Contains("/obj/", StringComparison.Ordinal) && !path.StartsWith(".nuget/", StringComparison.Ordinal)) inputs.Add(path);
                    }
                foreach (var dependency in current.Array("dependencies")) Add(nodes[dependency!.GetValue<string>()]);
            }
            Add(node); return inputs.Order(StringComparer.Ordinal);
        }
        foreach (var node in nodes.Values.OrderBy(node => node.String("project"), StringComparer.Ordinal))
            projects[Host.Relative(node.String("project"))] = new JsonObject
            {
                ["dependencies"] = Json.Strings(node.Array("dependencies").Select(id => Host.Relative(nodes[id!.GetValue<string>()].String("project"))).Order(StringComparer.Ordinal)),
                ["structural"] = Json.Strings(Structural(node)),
                ["sources"] = Json.Strings(node.Array("inputs").Where(input => NativePlan.SourceBody(input!)).Select(input => Host.Relative(input!.String("path"))).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal))
            };
        return new JsonObject { ["schemaVersion"] = 1, ["configuration"] = "Release", ["targetFramework"] = "net10.0", ["entry"] = Host.Relative(nodes[graph.Array("entryPoints")[0]!.GetValue<string>()].String("project")), ["projects"] = projects };
    }
    public static JsonNode Read(string path, string entry)
    {
        var layout = Json.Read(path);
        if (layout["schemaVersion"]?.GetValue<int>() != 1 || layout.String("entry") != entry || layout.String("configuration") != "Release" || layout.String("targetFramework") != "net10.0") throw new InvalidDataException("Invalid project layout configuration");
        var projects = layout["projects"]!.AsObject();
        if (!projects.ContainsKey(entry)) throw new InvalidDataException("Project layout entry missing");
        foreach (var (project, node) in projects)
        {
            Host.Safe(project);
            foreach (var source in node!.Array("sources")) Host.Safe(source!.GetValue<string>());
            foreach (var input in node!["structural"] as JsonArray ?? []) Host.Safe(input!.GetValue<string>());
            foreach (var dependency in node.Array("dependencies")) if (!projects.ContainsKey(dependency!.GetValue<string>())) throw new InvalidDataException("Project layout dependency missing");
        }
        return layout;
    }
    public static void Validate(JsonNode request)
    {
        var actual = Capture(Json.Read(Path.Combine(request.String("discovery"), "graph.json")));
        var declared = Read(request.String("layout"), actual.String("entry"));
        // Layouts exported before structural ownership was recorded retain the
        // conservative shared-input behavior until explicitly regenerated.
        foreach (var (project, node) in declared["projects"]!.AsObject())
            if (node!["structural"] is null && actual["projects"]?[project] is JsonObject actualNode) actualNode.Remove("structural");
        if (!JsonNode.DeepEquals(actual, declared)) throw new InvalidDataException("Project layout differs from MSBuild discovery; regenerate the layout");
        Json.Write(request.String("output"), new JsonObject { ["validated"] = true });
    }
}
