using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

internal static class NativePlan
{
    public static bool SourceBody(JsonNode input) => input.String("kind") == "source" && input.String("path").StartsWith("workspace/", StringComparison.Ordinal) && !input.String("path").StartsWith("workspace/.nuget/", StringComparison.Ordinal) && !input.String("path").Contains("/obj/", StringComparison.Ordinal) && input.String("path").EndsWith(".cs", StringComparison.Ordinal);
    public const string Policy = "evaluated-api-runtime-v2";
    public static Dictionary<string, JsonNode> Qualify(JsonNode graph)
    {
        var nodes = graph.Array("nodes").ToDictionary(n => n!.String("id"), n => n!, StringComparer.Ordinal);
        if (nodes.Count == 0 || graph.Array("entryPoints").Count != 1 || !nodes.ContainsKey(graph.Array("entryPoints")[0]!.GetValue<string>())) throw new InvalidDataException("One native graph entry required");
        var projects = new HashSet<string>(StringComparer.Ordinal);
        foreach (var node in nodes.Values)
        {
            var project = Host.Relative(node.String("project")); var folder = Path.GetDirectoryName(project)!;
            var framework = node.String("targetFramework"); var properties = node["globalProperties"]!.AsObject();
            if (!projects.Add(project) || properties.String("configuration") != "Release" || properties.Any(pair => pair.Key is not ("configuration" or "targetframework")) ||
                (properties["targetframework"]?.GetValue<string>() ?? framework) != framework || framework is not ("net10.0" or "netstandard2.0") || node.String("outputType") is not ("Library" or "Exe"))
                throw new InvalidDataException("Native graph requires unique selected Release projects");
            var expected = new JsonArray(new JsonObject { ["kind"] = "assembly", ["path"] = "workspace/" + Path.Combine(folder, "bin/Release", framework, Path.GetFileNameWithoutExtension(project) + ".dll") });
            if (Host.Relative(node["execution"]!.String("outputDirectory")) != Path.Combine(folder, "bin/Release", framework) || Host.Relative(node["execution"]!.String("referenceDirectory")) != Path.Combine(folder, "obj/Release", framework, "ref") || !JsonNode.DeepEquals(expected, node["outputs"])) throw new InvalidDataException("Unqualified native output layout");
            if (node.Array("dependencies").Any(d => !nodes.ContainsKey(d!.GetValue<string>()))) throw new InvalidDataException("Missing graph dependency");
            var dependencies = node.Array("dependencies").Select(d => nodes[d!.GetValue<string>()].String("project")).ToHashSet(StringComparer.Ordinal);
            if (Analyzers(node).Any(project => !dependencies.Contains(project))) throw new InvalidDataException("Analyzer reference is not a graph dependency");
        }
        return nodes;
    }
    private static IEnumerable<string> Analyzers(JsonNode node) => (node["execution"]?["analyzerReferences"] as JsonArray ?? []).Select(value => value!.GetValue<string>());
    public static void Materialize(string prepared, JsonNode graph, string output, string toolchain, bool includePayload = true)
    {
        var nodes = Qualify(graph); Directory.CreateDirectory(output);
        var implementations = new HashSet<string>(StringComparer.Ordinal);
        void RequireImplementation(JsonNode node)
        {
            if (!implementations.Add(node.String("project"))) return;
            foreach (var dependency in node.Array("dependencies")) RequireImplementation(nodes[dependency!.GetValue<string>()]);
        }
        var analyzerProjects = nodes.Values.SelectMany(Analyzers).ToHashSet(StringComparer.Ordinal);
        foreach (var node in nodes.Values)
            if (analyzerProjects.Contains(node.String("project")) || node.String("targetFramework") != "net10.0") RequireImplementation(node);
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
            var declaration = new JsonObject { ["dependencies"] = Json.Strings(node.Array("dependencies").Select(d => Host.Relative(nodes[d!.GetValue<string>()].String("project")))) };
            if (node.String("targetFramework") != "net10.0") { record["targetFramework"] = node.String("targetFramework"); declaration["targetFramework"] = node.String("targetFramework"); }
            if (implementations.Contains(node.String("project"))) { record["implementation"] = true; declaration["implementation"] = true; }
            var analyzers = Analyzers(node).Select(Host.Relative).ToArray();
            if (analyzers.Length != 0) { record["analyzers"] = Json.Strings(analyzers); declaration["analyzers"] = Json.Strings(analyzers); }
            records[project] = record; declaration["identity"] = Json.Digest(record); projects[project] = declaration;
        }
        if (!includePayload)
        {
            var payload = new JsonObject();
            foreach (var path in FileTree.Files(sourceRoot)) payload[Path.GetRelativePath(sourceRoot, path)] = FileTree.HashRegular(path).Digest;
            if (Directory.Exists(packageRoot)) foreach (var path in FileTree.Files(packageRoot)) payload[".nuget/packages/" + Path.GetRelativePath(packageRoot, path)] = FileTree.HashRegular(path).Digest;
            Json.Write(Path.Combine(output, "payload.json"), payload);
            Directory.CreateDirectory(Path.Combine(output, "project-records"));
            var bindings = new JsonObject();
            foreach (var (id, node) in nodes)
            {
                var project = Host.Relative(node.String("project"));
                bindings[project] = new JsonObject { ["record"] = "project-records/" + id + ".json", ["sources"] = Json.Strings(node.Array("inputs").Where(input => SourceBody(input!)).Select(input => Host.Relative(input!.String("path"))).Distinct().Order(StringComparer.Ordinal)) };
                Json.Write(Path.Combine(output, "project-records", id + ".json"), records[project]!);
            }
            var protectedSources = nodes.Values.SelectMany(node => node.Array("inputs")).Concat(graph["graphInputs"] as JsonArray ?? [])
                .Where(input => input!.String("path").StartsWith("workspace/", StringComparison.Ordinal) && input.String("kind") != "source")
                .Select(input => Host.Relative(input!.String("path"))).Distinct().Order(StringComparer.Ordinal);
            Json.Write(Path.Combine(output, "binding-index.json"), new JsonObject { ["policy"] = "project-bindings-v1", ["projects"] = bindings, ["protectedSources"] = Json.Strings(protectedSources), ["graphInputs"] = graph["graphInputs"]?.DeepClone() ?? new JsonArray() });
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
        if (request["project"] is not null && File.Exists(Path.Combine(discovery, "binding-index.json"))) { BindProjectSources(request); return; }
        var projectAction = request["project"] is not null;
        var input = projectAction ? discovery : output;
        Directory.CreateDirectory(output);
        // Per-project actions need only the bound replay plan, not another copy
        // of the complete graph and every project's package/identity metadata.
        // Bazel presents declared tree-artifact leaves as sandbox symlinks.
        foreach (var path in projectAction ? [] : FileTree.Files(discovery))
        {
            var target = Path.Combine(output, Path.GetRelativePath(discovery, path)); Host.Copy(Host.Real(path), target);
            FileTree.SetMode(target, FileTree.Mode(target) | UnixFileMode.UserWrite);
        }
        var graph = Json.Read(Path.Combine(input, "graph.json"));
        var pathComparer = OperatingSystem.IsMacOS() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;
        var sources = request.Array("sources").ToDictionary(n => Host.Safe(n!.String("destination")), n => n!.String("source"), pathComparer);
        RequireSourceOnly(graph, sources.Keys.ToHashSet(StringComparer.Ordinal));
        var payloadPath = Path.Combine(output, "payload.json");
        var inputPayload = Path.Combine(input, "payload.json");
        var payload = File.Exists(inputPayload) ? Json.Read(inputPayload) : null;
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
        var records = Json.Read(Path.Combine(input, "identity-records.json")); var manifest = Json.Read(Path.Combine(input, "manifest.json"));
        foreach (var (project, record) in records.AsObject())
        {
            if (Json.Digest(record!) != manifest["projects"]![project]!.String("identity")) throw new InvalidDataException("Corrupt discovery identity");
            foreach (var name in record!["inputs"]!.AsObject().Select(p => p.Key).ToArray()) if (hashes.TryGetValue(name, out var hash)) record["inputs"]![name] = hash;
            record!["graphInputs"] = graph["graphInputs"]?.DeepClone() ?? new JsonArray();
            manifest["projects"]![project]!["identity"] = Json.Digest(record);
        }
        if (request["project"] is { } selectedProject)
        {
            var project = selectedProject.GetValue<string>(); var projects = manifest["projects"]!.AsObject();
            if (!projects.ContainsKey(project) || !projects[project]!.Array("dependencies").Select(n => n!.GetValue<string>()).Order().SequenceEqual(request.Array("dependencies").Select(n => n!.GetValue<string>()).Order())) throw new InvalidDataException("Project layout differs from discovery");
            var node = graph.Array("nodes").Single(n => Host.Relative(n!.String("project")) == project)!;
            var expected = node.Array("inputs").Where(n => SourceBody(n!)).Select(n => Host.Relative(n!.String("path"))).ToHashSet(pathComparer);
            if (!expected.SetEquals(sources.Keys)) throw new InvalidDataException("Project source layout differs from discovery");
            var closure = new HashSet<string>(StringComparer.Ordinal);
            void Visit(string current) { if (!closure.Add(current)) return; foreach (var dependency in projects[current]!.Array("dependencies")) Visit(dependency!.GetValue<string>()); }
            Visit(project);
            foreach (var name in projects.Select(p => p.Key).ToArray()) if (!closure.Contains(name)) { projects.Remove(name); records.AsObject().Remove(name); }
            if (payload is null) throw new InvalidDataException("Project actions require direct payloads");
            PrunePayload(payload, records, sources.Keys, graph["graphInputs"] as JsonArray ?? []);
            Json.Write(payloadPath, payload);
            // Dependencies replay captured target results without loading their
            // SDK or NuGet imports; only the selected project needs restore data.
            Json.Write(Path.Combine(output, "restore.json"), records[project]!["restore"]!);
            Json.Write(Path.Combine(output, "entry.json"), new JsonObject { ["entry"] = project });
            Json.Write(Path.Combine(output, "manifest.json"), manifest);
            return;
        }
        Json.Write(Path.Combine(output, "identity-records.json"), records); Json.Write(Path.Combine(output, "manifest.json"), manifest); Json.Write(Path.Combine(output, "graph.json"), graph);
    }
    private static void PrunePayload(JsonNode payload, JsonNode records, IEnumerable<string> sources, JsonArray graphInputs)
    {
        var sourceNames = sources.ToHashSet(OperatingSystem.IsMacOS() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal);
        var requiredPayload = new HashSet<string>(StringComparer.Ordinal);
        void Require(string logical)
        {
            if (logical.StartsWith("workspace/", StringComparison.Ordinal)) requiredPayload.Add(Host.Relative(logical));
            else if (logical.StartsWith("packages/", StringComparison.Ordinal)) requiredPayload.Add(".nuget/" + logical);
        }
        foreach (var record in records.AsObject().Select(pair => pair.Value!))
        {
            foreach (var name in record["inputs"]!.AsObject().Select(pair => pair.Key)) Require(name);
            foreach (var package in record["packages"]!.Array("packages"))
                foreach (var file in package!.Array("files")) requiredPayload.Add(".nuget/packages/" + package.String("path") + "/" + file!.String("path"));
        }
        foreach (var item in graphInputs) Require(item!.String("path"));
        foreach (var name in payload.AsObject().Select(p => p.Key).ToArray())
            if (!requiredPayload.Contains(name) || name.EndsWith(".cs", StringComparison.Ordinal) && !name.StartsWith(".nuget/", StringComparison.Ordinal) && !sourceNames.Contains(name)) payload.AsObject().Remove(name);
    }
    private static void BindProjectSources(JsonNode request)
    {
        var discovery = request.String("discovery"); var output = request.String("output"); var project = request.String("project");
        var index = Json.Read(Path.Combine(discovery, "binding-index.json"));
        if (index.String("policy") != "project-bindings-v1") throw new InvalidDataException("Unknown project binding policy");
        var manifest = Json.Read(Path.Combine(discovery, "manifest.json")); var projects = manifest["projects"]!.AsObject();
        if (!projects.ContainsKey(project) || !projects[project]!.Array("dependencies").Select(n => n!.GetValue<string>()).Order().SequenceEqual(request.Array("dependencies").Select(n => n!.GetValue<string>()).Order())) throw new InvalidDataException("Project layout differs from discovery");
        var comparer = OperatingSystem.IsMacOS() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;
        var sources = request.Array("sources").ToDictionary(n => Host.Safe(n!.String("destination")), n => n!.String("source"), comparer);
        if (!index["projects"]![project]!.Array("sources").Select(value => value!.GetValue<string>()).ToHashSet(comparer).SetEquals(sources.Keys)) throw new InvalidDataException("Project source layout differs from discovery");
        if (index.Array("protectedSources").Any(value => sources.ContainsKey(value!.GetValue<string>()))) throw new InvalidDataException("Source-content split requires a compile-only input");
        var hashes = sources.ToDictionary(pair => "workspace/" + pair.Key, pair => FileTree.HashRegular(Host.Real(pair.Value)).Digest, comparer);
        var graphInputs = index.Array("graphInputs");
        foreach (var input in graphInputs) if (hashes.TryGetValue(input!.String("path"), out var hash)) input!["sha256"] = hash;
        var records = new JsonObject();
        void Visit(string selected)
        {
            if (records.ContainsKey(selected)) return;
            var record = Json.Read(Path.Combine(discovery, Host.Safe(index["projects"]![selected]!.String("record"))));
            if (Json.Digest(record) != projects[selected]!.String("identity")) throw new InvalidDataException("Corrupt discovery identity");
            foreach (var name in record["inputs"]!.AsObject().Select(pair => pair.Key).ToArray()) if (hashes.TryGetValue(name, out var hash)) record["inputs"]![name] = hash;
            record["graphInputs"] = graphInputs.DeepClone(); projects[selected]!["identity"] = Json.Digest(record);
            records[selected] = record;
            foreach (var dependency in projects[selected]!.Array("dependencies")) Visit(dependency!.GetValue<string>());
        }
        Visit(project);
        foreach (var name in projects.Select(pair => pair.Key).ToArray()) if (!records.ContainsKey(name)) projects.Remove(name);
        var payload = Json.Read(Path.Combine(discovery, "payload.json"));
        PrunePayload(payload, records, sources.Keys, graphInputs);
        foreach (var name in payload.AsObject().Select(pair => pair.Key).ToArray()) if (hashes.TryGetValue("workspace/" + name, out var hash)) payload[name] = hash;
        Directory.CreateDirectory(output);
        Json.Write(Path.Combine(output, "payload.json"), payload);
        Json.Write(Path.Combine(output, "manifest.json"), manifest);
        Json.Write(Path.Combine(output, "restore.json"), records[project]!["restore"]!);
        Json.Write(Path.Combine(output, "entry.json"), new JsonObject { ["entry"] = project });
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
