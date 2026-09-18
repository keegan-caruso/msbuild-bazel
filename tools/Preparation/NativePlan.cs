using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

internal static class NativePlan
{
    public const string Policy = "evaluated-api-runtime-v2";
    public static Dictionary<string, JsonNode> Qualify(JsonNode graph)
    {
        var nodes = graph.Array("nodes").ToDictionary(n => n!.String("id"), n => n!, StringComparer.Ordinal);
        if (nodes.Count == 0 || graph.Array("entryPoints").Count != 1 || !nodes.ContainsKey(graph.Array("entryPoints")[0]!.GetValue<string>())) throw new InvalidDataException("One native graph entry required");
        var projects = new HashSet<string>(StringComparer.Ordinal);
        foreach (var node in nodes.Values)
        {
            var project = Host.Relative(node.String("project")); var folder = Path.GetDirectoryName(project)!;
            var properties = new JsonObject { ["configuration"] = "Release", ["targetframework"] = "net10.0" };
            if (!projects.Add(project) || !JsonNode.DeepEquals(properties, node["globalProperties"]) || node.String("targetFramework") != "net10.0" || node.String("outputType") is not ("Library" or "Exe")) throw new InvalidDataException("Native graph requires unique Release/net10 projects");
            var expected = new JsonArray(new JsonObject { ["kind"] = "assembly", ["path"] = "workspace/" + Path.Combine(folder, "bin/Release/net10.0", Path.GetFileNameWithoutExtension(project) + ".dll") });
            if (Host.Relative(node["execution"]!.String("outputDirectory")) != Path.Combine(folder, "bin/Release/net10.0") || Host.Relative(node["execution"]!.String("referenceDirectory")) != Path.Combine(folder, "obj/Release/net10.0/ref") || !JsonNode.DeepEquals(expected, node["outputs"])) throw new InvalidDataException("Unqualified native output layout");
            if (node.Array("dependencies").Any(d => !nodes.ContainsKey(d!.GetValue<string>()))) throw new InvalidDataException("Missing graph dependency");
        }
        return nodes;
    }
    public static void Materialize(string prepared, JsonNode graph, string output, string toolchain, bool includePayload = true)
    {
        var nodes = Qualify(graph); Directory.CreateDirectory(output);
        var sourceRoot = Path.Combine(prepared, "src");
        if (includePayload) FileTree.Copy(sourceRoot, Path.Combine(output, "src"));
        var packageRoot = Path.Combine(prepared, "packages");
        if (includePayload && Directory.Exists(packageRoot)) FileTree.Copy(packageRoot, Path.Combine(output, "src/.nuget/packages"));
        var restore = new JsonObject(); var projects = new JsonObject(); var records = new JsonObject();
        foreach (var (id, node) in nodes)
        {
            var selected = new JsonObject();
            foreach (var (path, content) in Json.Read(Path.Combine(prepared, "restore", id + ".json")).AsObject())
                if (Path.GetFileName(path) == "project.assets.json" || path.EndsWith(".nuget.g.props", StringComparison.Ordinal) || path.EndsWith(".nuget.g.targets", StringComparison.Ordinal)) { selected[path] = content!.DeepClone(); restore[path] = content.DeepClone(); }
            var packages = Json.Read(Path.Combine(prepared, "package-manifests", id + ".json"));
            foreach (var package in packages.Array("packages"))
                foreach (var file in package!.Array("files"))
                {
                    var bytes = File.ReadAllBytes(Path.Combine(packageRoot, Host.Safe(package.String("path")), Host.Safe(file!.String("path"))));
                    if (bytes.LongLength != file!["size"]!.GetValue<long>() || Json.Sha(bytes) != file.String("sha256")) throw new InvalidDataException("Package payload changed");
                }
            var inputs = new JsonObject();
            foreach (var item in node.Array("inputs"))
            {
                var logical = item!.String("path");
                if (item.String("kind") == "package" || !logical.StartsWith("workspace/", StringComparison.Ordinal)) inputs[logical] = item!["sha256"]!.DeepClone();
                else
                {
                    var path = Host.Relative(logical);
                    if (!path.Contains("/obj/", StringComparison.Ordinal)) inputs[logical] = Json.Sha(File.ReadAllBytes(Path.Combine(sourceRoot, path)));
                }
            }
            foreach (var name in new[] { "global.json", "NuGet.Config", "NuGet.config", "Directory.Build.props", "Directory.Build.targets" })
                if (File.Exists(Path.Combine(sourceRoot, name))) inputs["workspace/" + name] = Json.Sha(File.ReadAllBytes(Path.Combine(sourceRoot, name)));
            var project = Host.Relative(node.String("project"));
            var record = new JsonObject { ["policy"] = Policy, ["inputs"] = inputs, ["restore"] = selected, ["packages"] = packages, ["configuration"] = node["globalProperties"]!.DeepClone(), ["graphInputs"] = graph["graphInputs"]?.DeepClone() ?? new JsonArray() };
            records[project] = record;
            projects[project] = new JsonObject { ["identity"] = Json.Digest(record), ["dependencies"] = Json.Strings(node.Array("dependencies").Select(d => Host.Relative(nodes[d!.GetValue<string>()].String("project")))) };
        }
        if (!includePayload)
        {
            var payload = new JsonObject();
            foreach (var path in FileTree.Files(sourceRoot)) payload[Path.GetRelativePath(sourceRoot, path)] = FileTree.HashRegular(path).Digest;
            if (Directory.Exists(packageRoot)) foreach (var path in FileTree.Files(packageRoot)) payload[".nuget/packages/" + Path.GetRelativePath(packageRoot, path)] = FileTree.HashRegular(path).Digest;
            Json.Write(Path.Combine(output, "payload.json"), payload);
        }
        Json.Write(Path.Combine(output, "identity-records.json"), records);
        Json.Write(Path.Combine(output, "manifest.json"), new JsonObject { ["policy"] = Policy, ["toolchain"] = toolchain, ["projects"] = projects });
        Json.Write(Path.Combine(output, "restore.json"), restore);
        Json.Write(Path.Combine(output, "entry.json"), new JsonObject { ["entry"] = Host.Relative(nodes[graph.Array("entryPoints")[0]!.GetValue<string>()].String("project")) });
        FileTree.Copy(Path.Combine(prepared, "package-manifests"), Path.Combine(output, "package-manifests"));
        Json.Write(Path.Combine(output, "graph.json"), graph);
    }
    public static void RequireSourceOnly(JsonNode graph, HashSet<string> names)
    {
        foreach (var item in graph.Array("nodes").SelectMany(n => n!.Array("inputs")).Concat(graph["graphInputs"] as JsonArray ?? []))
            if (item!.String("path").StartsWith("workspace/", StringComparison.Ordinal) && (names.Contains(Host.Relative(item.String("path"))) || OperatingSystem.IsMacOS() && names.Any(name => name.Equals(Host.Relative(item.String("path")), StringComparison.OrdinalIgnoreCase))) && item.String("kind") != "source")
                throw new InvalidDataException("Source-content split requires a compile-only input: " + item!.String("path"));
    }
    public static void BindSources(JsonNode request)
    {
        var output = request.String("output"); var discovery = request.String("discovery");
        // Bazel presents declared tree-artifact leaves as sandbox symlinks.
        foreach (var path in FileTree.Files(discovery))
        {
            var target = Path.Combine(output, Path.GetRelativePath(discovery, path)); Host.Copy(Host.Real(path), target);
            FileTree.SetMode(target, FileTree.Mode(target) | UnixFileMode.UserWrite);
        }
        var graph = Json.Read(Path.Combine(output, "graph.json"));
        var pathComparer = OperatingSystem.IsMacOS() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;
        var sources = request.Array("sources").ToDictionary(n => Host.Safe(n!.String("destination")), n => n!.String("source"), pathComparer);
        RequireSourceOnly(graph, sources.Keys.ToHashSet(StringComparer.Ordinal));
        var payloadPath = Path.Combine(output, "payload.json");
        var payload = File.Exists(payloadPath) ? Json.Read(payloadPath) : null;
        var hashes = sources.ToDictionary(p => "workspace/" + p.Key, p => FileTree.HashRegular(Host.Real(p.Value)).Digest, pathComparer);
        foreach (var (name, source) in sources)
        {
            if (payload is not null) continue;
            else if (File.Exists(Path.Combine(output, "src", name))) Host.Copy(source, Path.Combine(output, "src", name));
        }
        if (payload is not null)
        {
            foreach (var name in payload.AsObject().Select(p => p.Key).ToArray()) if (hashes.TryGetValue("workspace/" + name, out var hash)) payload[name] = hash;
            Json.Write(payloadPath, payload);
        }
        foreach (var item in graph.Array("nodes").SelectMany(n => n!.Array("inputs")).Concat(graph["graphInputs"] as JsonArray ?? []))
            if (hashes.TryGetValue(item!.String("path"), out var hash)) item!["sha256"] = hash;
        var records = Json.Read(Path.Combine(output, "identity-records.json")); var manifest = Json.Read(Path.Combine(output, "manifest.json"));
        foreach (var (project, record) in records.AsObject())
        {
            if (Json.Digest(record!) != manifest["projects"]![project]!.String("identity")) throw new InvalidDataException("Corrupt discovery identity");
            foreach (var name in record!["inputs"]!.AsObject().Select(p => p.Key).ToArray()) if (hashes.TryGetValue(name, out var hash)) record["inputs"]![name] = hash;
            record!["graphInputs"] = graph["graphInputs"]?.DeepClone() ?? new JsonArray();
            manifest["projects"]![project]!["identity"] = Json.Digest(record);
        }
        Json.Write(Path.Combine(output, "identity-records.json"), records); Json.Write(Path.Combine(output, "manifest.json"), manifest); Json.Write(Path.Combine(output, "graph.json"), graph);
    }
    public static JsonNode? Refresh(string plan, string workspace, JsonNode previous, JsonNode current)
    {
        var graph = Json.Read(Path.Combine(plan, "graph.json"));
        var inputs = graph.Array("nodes").SelectMany(n => n!.Array("inputs")).Concat(graph["graphInputs"] as JsonArray ?? []).Select(n => n!).ToArray();
        if (inputs.Any(i => i.String("kind") == "additional" || i.String("kind") == "resource" && (Path.GetExtension(i.String("path")) != ".xml" || !JsonNode.DeepEquals(i["metadata"], new JsonObject { ["LogicalName"] = Path.GetFileName(i.String("path")) })))) return null;
        var allowed = inputs.GroupBy(i => i.String("path")).Where(g => g.All(i => i.String("kind") == "source") && g.Key.EndsWith(".cs", StringComparison.Ordinal)).Select(g => g.Key).ToHashSet(StringComparer.Ordinal);
        if (!previous.AsObject().Select(p => p.Key).ToHashSet().SetEquals(current.AsObject().Select(p => p.Key))) return null;
        var changed = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var (path, before) in previous.AsObject())
        {
            var after = current[path]!;
            if (JsonNode.DeepEquals(before, after)) continue;
            if (!allowed.Contains("workspace/" + path) || before!.String("kind") != "file" || after.String("kind") != "file" || !JsonNode.DeepEquals(before!["mode"], after["mode"])) return null;
            changed["workspace/" + path] = after.String("sha256");
        }
        if (changed.Count == 0) return null;
        foreach (var input in inputs)
            if (changed.TryGetValue(input.String("path"), out var hash))
            {
                if (input.String("sha256") != previous[Host.Relative(input.String("path"))]!.String("sha256")) return null;
                input["sha256"] = hash;
            }
        foreach (var (logical, hash) in changed)
        {
            var path = Host.Relative(logical); var bytes = File.ReadAllBytes(Path.Combine(workspace, path));
            if (Json.Sha(bytes) != hash) throw new InvalidDataException("Source changed during refresh");
            File.WriteAllBytes(Path.Combine(plan, "src", path), bytes);
        }
        var records = Json.Read(Path.Combine(plan, "identity-records.json")); var manifest = Json.Read(Path.Combine(plan, "manifest.json"));
        foreach (var (project, record) in records.AsObject())
        {
            if (Json.Digest(record!) != manifest["projects"]![project]!.String("identity")) throw new InvalidDataException("Corrupt native identity record");
            foreach (var (logical, hash) in changed) if (record!["inputs"]!.AsObject().ContainsKey(logical)) record["inputs"]![logical] = hash;
            record!["graphInputs"] = graph["graphInputs"]?.DeepClone() ?? new JsonArray();
            manifest["projects"]![project]!["identity"] = Json.Digest(record);
        }
        Json.Write(Path.Combine(plan, "identity-records.json"), records); Json.Write(Path.Combine(plan, "manifest.json"), manifest); Json.Write(Path.Combine(plan, "graph.json"), graph);
        return graph;
    }
}
