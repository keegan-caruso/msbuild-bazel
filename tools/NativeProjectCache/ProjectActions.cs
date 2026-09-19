using System.Text.Json;
using System.Text.Json.Nodes;
using ActionRunner;

internal sealed record ComposeRequest(string Entry, string Output, string[] Bundles, string? EntryBundle = null, string[]? RuntimeBundles = null, string? MetadataOutput = null);

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
    internal static void Runtime(string bundle, string output, Artifact[] artifacts)
    {
        var results = Read(bundle);
        var stem = Path.Combine(Bin(results.Project, results.TargetFramework), Assembly(results.Project));
        var selected = artifacts.Where(item => item.Path == stem + ".dll" || item.Path == stem + ".pdb" || item.Path == stem + ".xml").ToArray();
        if (!selected.Any(item => item.Path == stem + ".dll")) throw new InvalidDataException("Project runtime assembly missing");
        if (Directory.Exists(output) && Directory.EnumerateFileSystemEntries(output).Any()) throw new InvalidDataException("Runtime projection requires an empty output");
        foreach (var item in selected) Files.Copy(Path.Combine(bundle, "artifacts", item.Path), Path.Combine(output, "artifacts", item.Path));
        Files.Copy(Path.Combine(bundle, "results.json"), Path.Combine(output, "results.json"));
        CompileBoundary.Seal(output);
    }
    internal static void Compose(string requestPath)
    {
        var request = JsonSerializer.Deserialize<ComposeRequest>(File.ReadAllText(requestPath), Options)!;
        if (Directory.Exists(request.Output) && Directory.EnumerateFileSystemEntries(request.Output).Any()) throw new InvalidDataException("Runtime composition requires an empty output");
        var bundles = request.EntryBundle is null
            ? request.Bundles.Select(Bundle).ToDictionary(path => Read(path).Project, StringComparer.Ordinal)
            : (request.RuntimeBundles ?? []).ToDictionary(path => Read(path).Project, StringComparer.Ordinal);
        if (request.EntryBundle is not null)
        {
            var entryBundle = Bundle(request.EntryBundle);
            if (Read(entryBundle).Project != request.Entry || !bundles.TryAdd(request.Entry, entryBundle)) throw new InvalidDataException("Invalid runtime entry bundle");
        }
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
        if (request.MetadataOutput is not null)
        {
            var bin = Bin(request.Entry, results[request.Entry].TargetFramework) + "/";
            var localization = Path.GetDirectoryName(request.Entry)! + "/Localization/";
            var application = Path.Combine(request.Output, "app"); Directory.CreateDirectory(application);
            foreach (var item in own.Values)
            {
                var relative = item.Path.StartsWith(bin, StringComparison.Ordinal) ? item.Path[bin.Length..]
                    : results[request.Entry].OrchardApplication && item.Path.StartsWith(localization, StringComparison.Ordinal) ? "Localization/" + item.Path[localization.Length..] : null;
                if (relative is null) continue;
                var source = replacements.GetValueOrDefault(item.Path, Path.Combine(bundles[request.Entry], "artifacts", item.Path));
                var destination = Path.Combine(application, relative);
                if (File.Exists(destination)) throw new InvalidDataException("Ambiguous application output");
                Files.Copy(source, destination);
            }
            if (results[request.Entry].OrchardApplication)
            {
                Directory.CreateDirectory(Path.Combine(application, "wwwroot"));
                using (File.Open(Path.Combine(application, "wwwroot/.rules_msbuild_keep"), FileMode.CreateNew)) { }
            }
            Files.NormalizeTree(request.Output);
            var metadata = request.MetadataOutput;
            if (Directory.Exists(metadata) && Directory.EnumerateFileSystemEntries(metadata).Any()) throw new InvalidDataException("Runtime metadata requires an empty output");
            Directory.CreateDirectory(metadata);
            Files.Copy(Path.Combine(bundles[request.Entry], "results.json"), Path.Combine(metadata, "results.json"));
            JsonFiles.Write(Path.Combine(metadata, "artifacts.json"), Directory.EnumerateFiles(application, "*", SearchOption.AllDirectories)
                .Order(StringComparer.Ordinal).Select(path => new Artifact(Path.GetRelativePath(application, path), new FileInfo(path).Length, Files.Hash(path))).ToArray());
            JsonFiles.Write(Path.Combine(metadata, "bundle.json"), new BundleSeal(1, Files.Hash(Path.Combine(metadata, "results.json")), Files.Hash(Path.Combine(metadata, "artifacts.json"))));
            Files.NormalizeTree(metadata);
            return;
        }
        var entry = Path.Combine(request.Output, "cache", results[request.Entry].Key);
        Files.CopyTree(bundles[request.Entry], entry);
        Files.NormalizeTree(entry);
        foreach (var (destination, source) in replacements) Files.Copy(source, Path.Combine(entry, "artifacts", destination));
        CompileBoundary.Seal(entry);
        var runtime = Path.Combine(request.Output, "runtime", Path.GetFileName(entry));
        Files.CopyTree(entry, runtime);
        Files.CopyTree(Path.Combine(runtime, "artifacts", Bin(request.Entry, results[request.Entry].TargetFramework)), Path.Combine(request.Output, "app"));
        if (results[request.Entry].OrchardApplication)
        {
            // Orchard's qualified application target creates an empty wwwroot.
            // ASP.NET initializes WebRootPath only if it exists; the media cache
            // needs it after setup. A marker preserves it through file-only cache
            // transports as well as ordinary copies of the composed application.
            var webRoot = Path.Combine(request.Output, "app/wwwroot");
            Directory.CreateDirectory(webRoot);
            using (File.Open(Path.Combine(webRoot, ".rules_msbuild_keep"), FileMode.CreateNew)) { }
            var localization = Path.Combine(runtime, "artifacts", Path.GetDirectoryName(request.Entry)!, "Localization");
            if (Directory.Exists(localization))
            {
                var destination = Path.Combine(request.Output, "app/Localization");
                if (Path.Exists(destination)) throw new InvalidDataException("Ambiguous localization output");
                Files.CopyTree(localization, destination);
            }
        }
    }
}
