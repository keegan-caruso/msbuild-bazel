using System.Text.Json.Nodes;

namespace ActionRunner;

internal sealed record BundleSeal(int SchemaVersion, string ResultsSha256, string ArtifactsSha256);

internal sealed record RuntimeAssemblyRequest(string Own, string[] Dependencies, string Output);

internal static class CompileBoundary
{
    // Only for sealed dependencies that remain immutable throughout one action.
    // Call VerifyUnchanged before publishing any result derived from this scope.
    internal sealed class ValidationScope
    {
        private readonly Dictionary<string, (Artifact[] Items, string Seal)> bundles = new(StringComparer.Ordinal);

        internal Artifact[] Read(string bundle)
        {
            if (bundles.TryGetValue(bundle, out var prior)) return prior.Items;
            var items = Validate(bundle);
            bundles.Add(bundle, (items, Files.Hash(Path.Combine(bundle, "bundle.json"))));
            return items;
        }

        internal void VerifyUnchanged()
        {
            foreach (var (bundle, prior) in bundles)
            {
                var current = Validate(bundle);
                if (Files.Hash(Path.Combine(bundle, "bundle.json")) != prior.Seal || !current.SequenceEqual(prior.Items))
                    throw new InvalidDataException("dependency bundle changed during build");
            }
        }
    }

    internal static Artifact[] Validate(string bundle)
    {
        var seal = JsonFiles.Read<BundleSeal>(Path.Combine(bundle, "bundle.json"));
        if (seal.SchemaVersion != 1 ||
            seal.ResultsSha256 != Files.Hash(Path.Combine(bundle, "results.json")) ||
            seal.ArtifactsSha256 != Files.Hash(Path.Combine(bundle, "artifacts.json")))
            throw new InvalidDataException("dependency bundle metadata corrupt");
        var items = JsonFiles.Read<Artifact[]>(Path.Combine(bundle, "artifacts.json"));
        if (items.Length == 0 || items.Any(item => item is null) || items.Select(item => item.Path).Distinct(StringComparer.Ordinal).Count() != items.Length)
            throw new InvalidDataException("empty or duplicate dependency artifacts");
        foreach (var item in items)
        {
            if (!Files.ValidRelativePath(item.Path)) throw new InvalidDataException("invalid artifact path");
            Files.Verify(Path.Combine(bundle, "artifacts", item.Path), item.Size, item.Sha256, "dependency artifact corrupt");
        }
        return items;
    }

    internal static void Seal(string output)
    {
        var items = Directory.EnumerateFiles(Path.Combine(output, "artifacts"), "*", SearchOption.AllDirectories)
            .Order(StringComparer.Ordinal).Select(path => new Artifact(
                Path.GetRelativePath(Path.Combine(output, "artifacts"), path), new FileInfo(path).Length, Files.Hash(path))).ToArray();
        JsonFiles.Write(Path.Combine(output, "artifacts.json"), items);
        JsonFiles.Write(Path.Combine(output, "bundle.json"), new
        {
            schemaVersion = 1,
            resultsSha256 = Files.Hash(Path.Combine(output, "results.json")),
            artifactsSha256 = Files.Hash(Path.Combine(output, "artifacts.json"))
        });
        Files.NormalizeTree(output);
    }

    public static void Project(string bundle, string output)
    {
        var items = Validate(bundle);
        var payload = JsonNode.Parse(File.ReadAllText(Path.Combine(bundle, "results.json")))!;
        var build = payload["targets"]!["Build"]!.AsArray();
        if (build.Count != 1) throw new InvalidDataException("reference projection requires one Build result");
        var assembly = Relative(build[0]!["spec"]!.GetValue<string>());
        var reference = Relative(build[0]!["metadata"]!["ReferenceAssembly"]!.GetValue<string>());
        if (!items.Any(item => item.Path == reference)) throw new InvalidDataException("reference assembly missing");
        var stableFiles = new HashSet<string>(StringComparer.Ordinal);
        foreach (var target in new[] { "GetCopyToOutputDirectoryItems", "GetCopyToPublishDirectoryItems", "GetNativeManifest" })
            foreach (var item in payload["targets"]![target]!.AsArray())
            {
                var path = Relative(item!["spec"]!.GetValue<string>());
                var prefix = assembly[..^4];
                if (path != prefix + ".deps.json" && path != prefix + ".runtimeconfig.json")
                    throw new InvalidDataException("runtime content requires full dependency bundle");
                if (!items.Any(artifact => artifact.Path == path)) throw new InvalidDataException("runtime metadata missing");
                stableFiles.Add(path);
            }
        if (Directory.Exists(output) && Directory.EnumerateFileSystemEntries(output).Any())
            throw new InvalidDataException("reference output already contains a prior attempt");
        Directory.CreateDirectory(output);
        foreach (var path in stableFiles)
            Files.Copy(Path.Combine(bundle, "artifacts", path), Path.Combine(output, "artifacts", path));
        Files.Copy(Path.Combine(bundle, "results.json"), Path.Combine(output, "results.json"));
        // Keep replay's Build identity/path metadata. Both compiler-visible paths
        // contain reference bytes; runtime assembly composition is a separate action.
        foreach (var path in new[] { reference, assembly })
            Files.Copy(Path.Combine(bundle, "artifacts", reference), Path.Combine(output, "artifacts", path));
        Seal(output);
    }

    private static string Relative(string token)
    {
        const string prefix = "${WORKSPACE}/";
        if (!token.StartsWith(prefix, StringComparison.Ordinal) || !Files.ValidRelativePath(token[prefix.Length..]))
            throw new InvalidDataException("invalid workspace artifact token");
        return token[prefix.Length..];
    }

    private static void MergeRuntimeMetadata(RuntimeAssemblyRequest request, string assembly)
    {
        var relative = Path.ChangeExtension(assembly, ".deps.json");
        var path = Path.Combine(request.Output, "artifacts", relative);
        if (!File.Exists(path)) throw new InvalidDataException("SDK runtime dependency metadata missing");
        var result = JsonNode.Parse(File.ReadAllText(path))!;
        var target = result["runtimeTarget"]!["name"]!.GetValue<string>();
        var targets = result["targets"]![target]!.AsObject();
        var libraries = result["libraries"]!.AsObject();
        foreach (var bundle in request.Dependencies)
        {
            var replay = JsonNode.Parse(File.ReadAllText(Path.Combine(bundle, "results.json")))!;
            var ownAssembly = Relative(replay["targets"]!["Build"]![0]!["spec"]!.GetValue<string>());
            var metadata = Path.Combine(bundle, "artifacts", Path.ChangeExtension(ownAssembly, ".deps.json"));
            if (!File.Exists(metadata)) throw new InvalidDataException("dependency runtime metadata missing");
            var dependency = JsonNode.Parse(File.ReadAllText(metadata))!;
            if (dependency["runtimeTarget"]!["name"]!.GetValue<string>() != target)
                throw new InvalidDataException("runtime target mismatch");
            foreach (var item in dependency["libraries"]!.AsObject())
            {
                if (item.Value!["type"]!.GetValue<string>() != "project")
                    throw new InvalidDataException("unqualified runtime library");
                if (libraries[item.Key] is { } prior && !JsonNode.DeepEquals(prior, item.Value))
                    throw new InvalidDataException("runtime library identity collision");
                libraries[item.Key] = item.Value.DeepClone();
            }
            foreach (var item in dependency["targets"]![target]!.AsObject())
            {
                if (targets[item.Key] is not JsonObject existing)
                {
                    targets[item.Key] = item.Value!.DeepClone();
                    continue;
                }
                // Retain consumer SDK assembly/file version metadata and enrich
                // it with the dependency's SDK-generated runtime graph edges.
                if (item.Value!["dependencies"] is JsonObject edges)
                {
                    var merged = existing["dependencies"] as JsonObject;
                    if (merged is null) existing["dependencies"] = merged = new JsonObject();
                    foreach (var edge in edges)
                    {
                        if (merged[edge.Key] is { } version && !JsonNode.DeepEquals(version, edge.Value))
                            throw new InvalidDataException("runtime dependency version collision");
                        merged[edge.Key] = edge.Value!.DeepClone();
                    }
                }
            }
        }
        JsonFiles.Write(path, result);
    }

    public static void Assemble(RuntimeAssemblyRequest request)
    {
        var own = Validate(request.Own);
        var payload = JsonNode.Parse(File.ReadAllText(Path.Combine(request.Own, "results.json")))!;
        var assembly = Relative(payload["targets"]!["Build"]![0]!["spec"]!.GetValue<string>());
        var runtime = Path.GetDirectoryName(assembly)!;
        var replacements = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var dependency in request.Dependencies)
        {
            var items = Validate(dependency);
            var replay = JsonNode.Parse(File.ReadAllText(Path.Combine(dependency, "results.json")))!;
            var producer = Relative(replay["targets"]!["Build"]![0]!["spec"]!.GetValue<string>());
            foreach (var item in items.Where(item => item.Path == producer ||
                item.Path == Path.ChangeExtension(producer, ".pdb") || item.Path == Path.ChangeExtension(producer, ".xml")))
            {
                var dependencyRuntime = item.Path.IndexOf("/bin/Release/net10.0/", StringComparison.Ordinal);
                if (dependencyRuntime < 0) throw new InvalidDataException("unqualified runtime layout");
                var relative = item.Path[(dependencyRuntime + "/bin/Release/net10.0/".Length)..];
                var destination = Path.Combine(runtime, relative);
                // The qualified graph has ordinary copy-local project references
                // only. Its entire project runtime closure must accompany the entry.
                if (Path.GetExtension(destination) is not (".dll" or ".pdb" or ".xml")) continue;
                if (destination == assembly) throw new InvalidDataException("dependency shadows consumer assembly");
                if (replacements.TryGetValue(destination, out var prior) && prior != item.Sha256)
                    throw new InvalidDataException("runtime dependency artifact collision");
                replacements[destination] = item.Sha256;
            }
        }
        if (Directory.Exists(request.Output) && Directory.EnumerateFileSystemEntries(request.Output).Any())
            throw new InvalidDataException("runtime output already contains a prior attempt");
        // Do not copy an old commit marker into a partially assembled output.
        foreach (var item in own)
            Files.Copy(Path.Combine(request.Own, "artifacts", item.Path), Path.Combine(request.Output, "artifacts", item.Path));
        Files.Copy(Path.Combine(request.Own, "results.json"), Path.Combine(request.Output, "results.json"));
        Files.NormalizeTree(request.Output);
        foreach (var dependency in request.Dependencies)
            foreach (var item in JsonFiles.Read<Artifact[]>(Path.Combine(dependency, "artifacts.json")))
            {
                var index = item.Path.IndexOf("/bin/Release/net10.0/", StringComparison.Ordinal);
                if (index < 0) continue;
                var destination = Path.Combine(runtime, item.Path[(index + "/bin/Release/net10.0/".Length)..]);
                if (replacements.TryGetValue(destination, out var selectedHash) && selectedHash == item.Sha256 && replacements.Remove(destination))
                    Files.Copy(Path.Combine(dependency, "artifacts", item.Path), Path.Combine(request.Output, "artifacts", destination));
            }
        MergeRuntimeMetadata(request, assembly);
        Seal(request.Output);
    }
}
