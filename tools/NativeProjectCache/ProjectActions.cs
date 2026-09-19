using System.Text.Json;
using System.Text.Json.Nodes;
using ActionRunner;

internal sealed record ComposeRequest(string Entry, string Output, string[] Bundles);

// Bazel compile dependencies carry a stable API projection. Real implementation
// bytes are restored only by the final runtime action, without invoking MSBuild.
internal static class ProjectActions
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true };
    private static string Bin(string project, string framework) => Path.Combine(Path.GetDirectoryName(project)!, "bin/Release", framework);
    private static string Assembly(string project) => Path.GetFileNameWithoutExtension(project);
    internal static Results Read(string bundle)
    {
        var result = JsonSerializer.Deserialize<Results>(File.ReadAllText(Path.Combine(bundle, "results.json")), Options) ?? throw new InvalidDataException("Missing project results");
        if (result.TargetFramework is not ("net10.0" or "netstandard2.0") || !Files.ValidRelativePath(result.Project) || result.Key.Length != 64 || result.Key.Any(character => !char.IsAsciiHexDigit(character)) || string.IsNullOrEmpty(result.Inputs) || string.IsNullOrEmpty(result.Toolchain)) throw new InvalidDataException("Invalid project bundle identity");
        return result;
    }
    internal static string Bundle(string output) => Directory.GetDirectories(Path.Combine(output, "cache")).Single();
    private static JsonNode? Canonical(JsonNode? node) => node switch
    {
        JsonObject value => new JsonObject(value.OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => KeyValuePair.Create(p.Key, Canonical(p.Value)))),
        JsonArray value => new JsonArray(value.Select(Canonical).ToArray()),
        _ => node?.DeepClone()
    };
    internal static void Project(string bundle, string output, Dictionary<string, string> dependencies, string identity, bool fullImplementation = false)
    {
        var results = Read(bundle); var producers = new Dictionary<string, string>(dependencies, StringComparer.Ordinal) { [results.Project] = bundle };
        var implementations = producers.Keys.SelectMany(project => new[] { ".dll", ".pdb", ".xml" }.Select(extension => KeyValuePair.Create(Path.Combine(Bin(results.Project, results.TargetFramework), Assembly(project) + extension), project))).ToDictionary();
        foreach (var artifact in CompileBoundary.Validate(bundle))
        {
            var destination = Path.Combine(output, "artifacts", artifact.Path);
            if (fullImplementation || !implementations.TryGetValue(artifact.Path, out var project)) Files.Copy(Path.Combine(bundle, "artifacts", artifact.Path), destination);
            else if (Path.GetExtension(artifact.Path) == ".dll") RuntimeContract.Write(Path.Combine(producers[project], "artifacts", Bin(project, Read(producers[project]).TargetFramework), Assembly(project) + ".dll"), destination);
            else { Directory.CreateDirectory(Path.GetDirectoryName(destination)!); File.WriteAllBytes(destination, []); }
        }
        var metadata = JsonSerializer.SerializeToNode(results with { Key = identity, Inputs = identity }, Options)!;
        File.WriteAllText(Path.Combine(output, "results.json"), Canonical(metadata)!.ToJsonString(Options));
        CompileBoundary.Seal(output);
    }
    internal static void Compose(string requestPath)
    {
        var request = JsonSerializer.Deserialize<ComposeRequest>(File.ReadAllText(requestPath), Options)!;
        if (Directory.Exists(request.Output) && Directory.EnumerateFileSystemEntries(request.Output).Any()) throw new InvalidDataException("Runtime composition requires an empty output");
        var bundles = request.Bundles.Select(Bundle).ToDictionary(path => Read(path).Project, StringComparer.Ordinal);
        // Validate each producer once. Only the requested entry needs a composed
        // runtime; Bazel already owns every project's independent compile bundle.
        var artifacts = bundles.ToDictionary(pair => pair.Key, pair => CompileBoundary.Validate(pair.Value).ToDictionary(item => item.Path, StringComparer.Ordinal), StringComparer.Ordinal);
        var results = bundles.ToDictionary(pair => pair.Key, pair => Read(pair.Value), StringComparer.Ordinal);
        var toolchains = results.Values.Select(result => result.Toolchain).Distinct().ToArray();
        if (toolchains.Length != 1 || toolchains[0] is null) throw new InvalidDataException("Project toolchains differ");
        var own = artifacts[request.Entry];
        var replacements = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var (project, bundle) in bundles.Where(pair => pair.Key != request.Entry))
        {
            foreach (var extension in new[] { ".dll", ".pdb", ".xml" })
            {
                var destination = Path.Combine(Bin(request.Entry, results[request.Entry].TargetFramework), Assembly(project) + extension);
                if (!own.ContainsKey(destination)) continue;
                var source = Path.Combine(Bin(project, results[project].TargetFramework), Assembly(project) + extension);
                if (!artifacts[project].ContainsKey(source) || !replacements.TryAdd(destination, Path.Combine(bundle, "artifacts", source))) throw new InvalidDataException("Ambiguous or missing current runtime artifact");
            }
        }
        var entry = Path.Combine(request.Output, "cache", results[request.Entry].Key);
        Files.CopyTree(bundles[request.Entry], entry);
        Files.NormalizeTree(entry);
        foreach (var (destination, source) in replacements) Files.Copy(source, Path.Combine(entry, "artifacts", destination));
        CompileBoundary.Seal(entry);
        var runtime = Path.Combine(request.Output, "runtime", Path.GetFileName(entry));
        Files.CopyTree(entry, runtime);
        Files.CopyTree(Path.Combine(runtime, "artifacts", Bin(request.Entry, results[request.Entry].TargetFramework)), Path.Combine(request.Output, "app"));
    }
}
