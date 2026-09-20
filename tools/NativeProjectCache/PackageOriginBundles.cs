using System.Text.Json.Nodes;
using ActionRunner;
using RulesMSBuild;

// Version 3 retains the logical artifact index but transports package provenance
// instead of duplicate package bytes. Every consumer resolves declared inputs.
internal sealed class PackageOriginBundles(IReadOnlyDictionary<string, string> packages)
{
    private sealed record View(Artifact[] Artifacts, Dictionary<string, string> Origins, string Seal, HashSet<string> Paths);
    private readonly Dictionary<string, View> views = new(StringComparer.Ordinal);

    private static void ValidateTransport(string bundle)
    {
        var members = Directory.EnumerateFiles(bundle, "*", SearchOption.AllDirectories)
            .ToDictionary(path => Path.GetRelativePath(bundle, path), StringComparer.Ordinal);
        BundleIntegrity.Validate(members.Keys, name => File.ReadAllBytes(members[name]));
    }

    internal static bool IsSparse(string bundle) => JsonFiles.Read<BundleSeal>(Path.Combine(bundle, "bundle.json")).SchemaVersion == 3;

    internal static (int Files, long Bytes) Compact(string bundle, IReadOnlyDictionary<string, string> packageHashes)
    {
        ValidateTransport(bundle);
        if (JsonFiles.Read<BundleSeal>(Path.Combine(bundle, "bundle.json")).SchemaVersion != 1) throw new InvalidDataException("Expected dense package output");
        var byHash = packageHashes.OrderBy(pair => pair.Key, StringComparer.Ordinal).GroupBy(pair => pair.Value, StringComparer.Ordinal)
            .ToDictionary(group => group.Key, group => group.First().Key, StringComparer.Ordinal);
        var selected = JsonFiles.Read<Artifact[]>(Path.Combine(bundle, "artifacts.json"))
            .Where(item => item.Size > 0 && byHash.ContainsKey(item.Sha256)).ToArray();
        if (selected.Length == 0) return (0, 0);
        var origins = selected.ToDictionary(item => item.Path, item => byHash[item.Sha256], StringComparer.Ordinal);
        var originPath = Path.Combine(bundle, "package-origins.json");
        JsonFiles.Write(originPath, origins);
        var sealPath = Path.Combine(bundle, "bundle.json");
        var seal = JsonNode.Parse(File.ReadAllText(sealPath))!;
        seal["schemaVersion"] = 3;
        seal["packageOriginsSha256"] = Files.Hash(originPath);
        foreach (var item in selected) File.Delete(Path.Combine(bundle, "artifacts", item.Path));
        File.WriteAllText(sealPath, seal.ToJsonString());
        ValidateTransport(bundle);
        Files.NormalizeTree(bundle);
        return (selected.Length, selected.Sum(item => item.Size));
    }

    private Dictionary<string, string> Origins(string bundle) => IsSparse(bundle)
        ? JsonFiles.Read<Dictionary<string, string>>(Path.Combine(bundle, "package-origins.json")) : new(StringComparer.Ordinal);

    private string Resolve(string bundle, string path, Dictionary<string, string> origins)
    {
        if (!origins.TryGetValue(path, out var package)) return Path.Combine(bundle, "artifacts", path);
        if (!packages.TryGetValue(package, out var source)) throw new InvalidDataException("Undeclared package origin: " + package);
        return source;
    }

    private View Validate(string bundle)
    {
        var sparse = IsSparse(bundle);
        if (sparse) ValidateTransport(bundle);
        var origins = Origins(bundle);
        var items = sparse ? JsonFiles.Read<Artifact[]>(Path.Combine(bundle, "artifacts.json")) : CompileBoundary.Validate(bundle);
        foreach (var item in items)
            if (origins.ContainsKey(item.Path)) Files.Verify(Resolve(bundle, item.Path, origins), item.Size, item.Sha256, "Package origin bytes differ");
        return new(items, origins, Files.Hash(Path.Combine(bundle, "bundle.json")), items.Select(item => item.Path).ToHashSet(StringComparer.Ordinal));
    }

    internal Artifact[] Read(string bundle)
    {
        if (!views.TryGetValue(bundle, out var view)) views.Add(bundle, view = Validate(bundle));
        return view.Artifacts;
    }

    internal string Source(string bundle, string path)
    {
        Read(bundle);
        if (!views[bundle].Paths.Contains(path)) throw new InvalidDataException("Undeclared artifact path");
        return Resolve(bundle, path, views[bundle].Origins);
    }

    internal string Expand(string bundle, string destination)
    {
        if (!IsSparse(bundle)) return bundle;
        var items = Read(bundle);
        Directory.CreateDirectory(destination);
        foreach (var name in new[] { "results.json", "artifacts.json" }) Files.Copy(Path.Combine(bundle, name), Path.Combine(destination, name));
        foreach (var item in items)
        {
            var target = Path.Combine(destination, "artifacts", item.Path);
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            File.CreateSymbolicLink(target, Path.GetFullPath(Source(bundle, item.Path)));
        }
        JsonFiles.Write(Path.Combine(destination, "bundle.json"), new BundleSeal(1, Files.Hash(Path.Combine(destination, "results.json")), Files.Hash(Path.Combine(destination, "artifacts.json"))));
        return destination;
    }

    internal void VerifyUnchanged()
    {
        foreach (var (bundle, prior) in views.Where(pair => pair.Value.Origins.Count > 0))
        {
            var current = Validate(bundle);
            if (current.Seal != prior.Seal || !current.Artifacts.SequenceEqual(prior.Artifacts)) throw new InvalidDataException("Package-origin bundle changed during action");
        }
    }
}
