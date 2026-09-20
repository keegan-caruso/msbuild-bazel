using System.Text.Json;
using Microsoft.Build.Execution;
using NuGet.Versioning;

internal static class PackageDeclarations
{
    private static void Version(string value, string locked, string id)
    {
        if (value.Length == 0) return;
        var valid = NuGetVersion.TryParse(value, out var exact)
            ? exact == NuGetVersion.Parse(locked)
            : VersionRange.TryParse(value, out var range) && range.Satisfies(NuGetVersion.Parse(locked));
        if (!valid) throw new InvalidDataException("PackageReference version disagrees with lock: " + id);
    }
    internal static void Validate(Request r, ProjectInstance evaluated)
    {
        var packages = r.Packages.ToDictionary(p => p.Id, StringComparer.OrdinalIgnoreCase);
        var privacy = new Dictionary<string, string>(r.PackagePrivateAssets ?? new(), StringComparer.OrdinalIgnoreCase);
        foreach (var item in evaluated.GetItems("_BazelOriginalPackageReference"))
        {
            if (!packages.TryGetValue(item.EvaluatedInclude, out var package) || !r.DeclaredPackages.Contains(item.EvaluatedInclude, StringComparer.OrdinalIgnoreCase))
                throw new InvalidDataException("Undeclared PackageReference: " + item.EvaluatedInclude);
            foreach (var name in new[] { "Aliases", "VersionOverride", "GeneratePathProperty" })
                if (item.GetMetadataValue(name).Length > 0) throw new InvalidDataException("Unsupported PackageReference metadata: " + name);
            Version(item.GetMetadataValue("Version"), package.Version, package.Id);
            var actual = item.GetMetadataValue("PrivateAssets").ToLowerInvariant();
            if (actual.Length == 0) actual = "none";
            if (actual is not ("all" or "none") || actual != privacy.GetValueOrDefault(package.Id, "none"))
                throw new InvalidDataException("PackageReference PrivateAssets disagrees with package_private_assets: " + package.Id);
        }
        foreach (var item in evaluated.GetItems("_BazelOriginalPackageVersion"))
            if (packages.TryGetValue(item.EvaluatedInclude, out var package)) Version(item.GetMetadataValue("Version"), package.Version, package.Id);
    }
    internal static void ValidateRestored(Session s)
    {
        using var assets = JsonDocument.Parse(File.ReadAllText(Path.Combine(s.State, "obj", "project.assets.json")));
        var packages = s.Request.Packages.ToDictionary(p => p.Id, StringComparer.OrdinalIgnoreCase);
        foreach (var library in assets.RootElement.GetProperty("libraries").EnumerateObject())
        {
            if (library.Value.GetProperty("type").GetString() != "package") continue;
            var parts = library.Name.Split('/');
            if (parts.Length != 2 || !packages.TryGetValue(parts[0], out var declared) || NuGetVersion.Parse(parts[1]) != NuGetVersion.Parse(declared.Version))
                throw new InvalidDataException("Restored package differs from declared lock: " + library.Name);
        }
    }
}
