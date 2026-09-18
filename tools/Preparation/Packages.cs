using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Xml;
using System.Xml.Linq;

namespace RulesMSBuild.Preparation;

internal sealed class Packages(string workspace, string output, string root)
{
    private readonly JsonNode pins = Json.Read(Path.Combine(root, "tools/pilot-package-policy.json"));
    private sealed record Stamp(long Length, long Written, long Created, FileAttributes Attributes, string Target);
    private sealed record Observation(Stamp Stamp, string Hash);
    private readonly Dictionary<string, Observation?> observed = new(StringComparer.Ordinal);

    private static Stamp Signature(string path)
    {
        var info = new FileInfo(path);
        return new(info.Length, info.LastWriteTimeUtc.Ticks, info.CreationTimeUtc.Ticks, info.Attributes, Host.Real(path));
    }
    private readonly Dictionary<string, (string Hash, JsonObject Record, string[] Paths)> staged = new(StringComparer.Ordinal);

    private byte[] Read(string path)
    {
        var before = Signature(path);
        var data = File.ReadAllBytes(path);
        if (before != Signature(path)) throw new InvalidDataException("package changed while reading: " + path);
        var value = new Observation(before, Json.Sha(data));
        if (observed.TryGetValue(path, out var previous) && previous != value) throw new InvalidDataException("package changed during preparation: " + path);
        observed[path] = value;
        return data;
    }
    public void Verify()
    {
        foreach (var (path, value) in observed)
            if (value is null ? File.Exists(path) : !File.Exists(path) || Signature(path) != value.Stamp || Json.Sha(File.ReadAllBytes(path)) != value.Hash || Signature(path) != value.Stamp)
                throw new InvalidDataException("package changed during preparation: " + path);
    }
    private static string Privacy(string? value)
    {
        var flags = (value ?? "").Split([';', ','], StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries).Select(v => v.ToLowerInvariant()).ToHashSet();
        if (flags.Count == 0 || flags.SetEquals(["contentfiles", "analyzers", "build"])) return "default";
        if (flags.SetEquals(["all"])) return "all";
        if (flags.SetEquals(["none"])) return "none";
        throw new InvalidDataException("unsupported-package: PrivateAssets must be default, all or none");
    }
    public JsonObject Plan(string project, string assetsFile, string framework)
    {
        var assets = Json.Read(Path.Combine(workspace, assetsFile));
        var selected = assets["targets"]?[framework] as JsonObject ?? throw new InvalidDataException("stale-restore: selected package target missing");
        var libraries = new JsonObject();
        foreach (var (name, item) in assets["libraries"]!.AsObject())
            if (item!.String("type") == "package" && selected.ContainsKey(name)) libraries.Add(name, item!.DeepClone());
        if (framework == "net8.0")
        {
            var pack = assets["project"]!["frameworks"]![framework]!.Array("downloadDependencies").Single(p => p!.String("name") == "Microsoft.NETCore.App.Ref")!;
            if (pack.String("version").Replace(" ", "", StringComparison.Ordinal) != "[8.0.30,8.0.30]") throw new InvalidDataException("unsupported-framework-pack: expected Microsoft.NETCore.App.Ref 8.0.30");
            libraries["Microsoft.NETCore.App.Ref/8.0.30"] = new JsonObject { ["type"] = "package", ["path"] = "microsoft.netcore.app.ref/8.0.30", ["sha512"] = pins["microsoft.netcore.app.ref/8.0.30"]!["restoreContentHash"]!.DeepClone() };
        }
        var source = Path.Combine(workspace, project);
        if (!File.Exists(source) || !Host.Within(Host.Real(source), workspace)) throw new InvalidDataException("missing-input: missing or escaping input: workspace/" + project);
        XDocument tree;
        try { tree = XDocument.Load(source); }
        catch (XmlException error) { throw new InvalidDataException("stale-manifest: stale graph input: workspace/" + project, error); }
        var restored = assets["project"]?["frameworks"]?[framework] ?? throw new InvalidDataException("stale-restore: selected project framework missing");
        var direct = (restored["dependencies"] as JsonObject ?? []).ToDictionary(p => p.Key, p => p.Value!, StringComparer.OrdinalIgnoreCase);
        foreach (var reference in tree.Descendants().Where(e => e.Name.LocalName == "PackageReference"))
        {
            if (reference.AncestorsAndSelf().Any(e => e.Attribute("Condition") is not null)) continue;
            var id = (string?)reference.Attribute("Include") ?? (string?)reference.Attribute("Update");
            if (id is null) continue;
            var version = (string?)reference.Attribute("Version");
            if (version is not null)
            {
                var chosen = version.StartsWith('[') && version.EndsWith(']') && !version.Contains(',') ? version[1..^1] : pins[(id + "/" + version).ToLowerInvariant()] is not null ? version : throw new InvalidDataException("unsupported-package: exact inline version or qualified pilot version required");
                if (!libraries.Any(p => p.Key.Equals(id + "/" + chosen, StringComparison.OrdinalIgnoreCase))) throw new InvalidDataException("stale-restore: package reference differs from restored version");
            }
            string? Metadata(string name) => (string?)reference.Attribute(name) ?? reference.Elements().FirstOrDefault(e => e.Name.LocalName == name)?.Value;
            var current = Metadata("PrivateAssets");
            if (current is not null && !current.Contains("$(", StringComparison.Ordinal) && !current.Contains("@(", StringComparison.Ordinal) &&
                (!direct.TryGetValue(id, out var saved) || Privacy(current) != Privacy(saved["suppressParent"]?.GetValue<string>())))
                throw new InvalidDataException("stale-restore: PrivateAssets differs from restore: " + id);
            foreach (var (name, allowed) in new[] { ("IncludeAssets", "all"), ("ExcludeAssets", "none") })
            {
                var value = Metadata(name);
                if (string.IsNullOrEmpty(value) || value.Contains("$(", StringComparison.Ordinal) || value.Contains("@(", StringComparison.Ordinal)) continue;
                var flags = string.Join(';', value.Split([';', ','], StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries).Select(v => v.ToLowerInvariant()).Distinct().Order(StringComparer.Ordinal));
                if (flags != allowed && !(name == "IncludeAssets" && flags == "analyzers;build")) throw new InvalidDataException("unsupported-package: nondefault " + name);
            }
        }
        foreach (var (identity, library) in libraries)
        {
            if (library?["path"] is null || library?["sha512"] is null) throw new InvalidDataException("unsupported-package: incomplete restored package metadata");
            if (selected[identity] is not JsonObject entry) continue;
            foreach (var role in new[] { "native", "runtimeTargets", "resource", "build", "buildMultiTargeting", "buildTransitive", "contentFiles" })
                if (entry[role] is JsonObject { Count: > 0 } && !Allowed(identity, "assetRoles", role.ToLowerInvariant())) throw new InvalidDataException("unsupported-package: only managed ref/lib assets are supported");
        }
        return libraries;
    }
    private bool Allowed(string identity, string field, string value) => (pins[identity.ToLowerInvariant()]?[field] as JsonArray)?.Any(v => v!.GetValue<string>() == value) == true;
    public (string Manifest, string[] Paths) Stage(string project, string assets, string framework, string node)
    {
        var manifest = new JsonObject { ["schemaVersion"] = 1, ["packages"] = new JsonArray() };
        var paths = new List<string>();
        foreach (var (identity, libraryNode) in Plan(project, assets, framework).OrderBy(p => p.Key, StringComparer.Ordinal))
        {
            var library = libraryNode!;
            var split = identity.Split('/');
            if (split.Length != 2) throw new InvalidDataException("unsupported-package: invalid package path");
            var (id, version) = (split[0], split[1]);
            var relative = Host.Safe(id.ToLowerInvariant() + "/" + version);
            if (library.String("path") != relative) throw new InvalidDataException("unsupported-package: invalid package path");
            if (staged.TryGetValue(relative, out var previous))
            {
                if (previous.Hash != library.String("sha512")) throw new InvalidDataException("hash-mismatch: package archive disagrees with restore");
                var record = previous.Record.DeepClone(); record["id"] = id;
                manifest.Array("packages").Add(record); paths.AddRange(previous.Paths); continue;
            }
            var localPaths = new List<string>();
            var folder = Path.Combine(workspace, ".nuget/packages", relative);
            var archiveName = id.ToLowerInvariant() + "." + version + ".nupkg";
            var raw = Read(Path.Combine(folder, archiveName));
            var sha512 = Convert.ToBase64String(SHA512.HashData(raw));
            var pin = pins[identity.ToLowerInvariant()];
            if ((pin?["restoreContentHash"]?.GetValue<string>() ?? sha512) != library.String("sha512")) throw new InvalidDataException("hash-mismatch: package archive disagrees with restore");
            if (pin is not null && Json.Sha(raw) != pin.String("archiveSha256")) throw new InvalidDataException("hash-mismatch: package archive differs from qualified pilot pin");
            var files = new JsonArray(); var seen = new HashSet<string>(StringComparer.Ordinal);
            void Write(string name, byte[] data)
            {
                if (!seen.Add(name)) throw new InvalidDataException("duplicate archive entry: " + name);
                var path = "packages/" + relative + "/" + name;
                Directory.CreateDirectory(Path.GetDirectoryName(Path.Combine(output, path))!);
                File.WriteAllBytes(Path.Combine(output, path), data);
                localPaths.Add(path);
                files.Add(new JsonObject { ["path"] = name, ["size"] = data.Length, ["sha256"] = Json.Sha(data) });
            }
            using (var zip = new ZipArchive(new MemoryStream(raw)))
                foreach (var entry in zip.Entries)
                {
                    if (entry.FullName.EndsWith('/')) continue;
                    var name = entry.FullName.Replace("%2B", "+", StringComparison.OrdinalIgnoreCase);
                    if (name.EndsWith(".nuspec", StringComparison.Ordinal)) name = name.ToLowerInvariant();
                    Host.Safe(name);
                    var parts = name.Split('/');
                    var analyzer = (name.StartsWith("analyzers/dotnet/cs/", StringComparison.Ordinal) && parts.Length == 4 || name.StartsWith("analyzers/dotnet/", StringComparison.Ordinal) && parts.Length == 3) && name.EndsWith(".dll", StringComparison.Ordinal);
                    if (!analyzer && new[] { "runtimes", "native", "analyzers", "build", "buildtransitive", "buildmultitargeting", "content", "contentfiles", "tools" }.Contains(parts[0].ToLowerInvariant()) && !Allowed(identity, "additionalRoots", parts[0].ToLowerInvariant())) throw new InvalidDataException("unsupported-package: only managed ref/lib payloads supported");
                    using var stream = entry.Open(); using var buffer = new MemoryStream(); stream.CopyTo(buffer); var data = buffer.ToArray();
                    var source = Path.Combine(folder, name);
                    if (!File.Exists(source))
                    {
                        if (name is not ("_rels/.rels" or "[Content_Types].xml") && !name.StartsWith("package/services/metadata/core-properties/", StringComparison.Ordinal)) throw new InvalidDataException("missing-input: " + source);
                        observed.TryAdd(source, null);
                    }
                    else if (!Read(source).AsSpan().SequenceEqual(data)) throw new InvalidDataException("hash-mismatch: package payload " + name);
                    Write(name, data);
                }
            if (pin is not null) Write(archiveName, raw);
            Write(archiveName + ".sha512", Encoding.ASCII.GetBytes(sha512));
            var package = new JsonObject { ["id"] = id, ["version"] = version, ["path"] = relative, ["archiveSha256"] = Json.Sha(raw), ["files"] = files };
            manifest.Array("packages").Add(package);
            staged[relative] = (library.String("sha512"), package, localPaths.ToArray());
            paths.AddRange(localPaths);
        }
        var target = "package-manifests/" + node + ".json";
        Directory.CreateDirectory(Path.Combine(output, "package-manifests")); Json.Write(Path.Combine(output, target), manifest);
        return (target, paths.Order(StringComparer.Ordinal).ToArray());
    }
}
