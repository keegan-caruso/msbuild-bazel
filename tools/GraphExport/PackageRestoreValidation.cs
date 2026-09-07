using System.Text.Json;
using Microsoft.Build.Execution;

internal static class PackageRestoreValidation
{
    public static void Validate(ProjectInstance project, JsonElement assets)
    {
        var references = project.GetItems("PackageReference").ToArray();
        var restored = new Dictionary<string, JsonElement>(StringComparer.OrdinalIgnoreCase);
        if (!assets.TryGetProperty("project", out var restoreProject) ||
            !restoreProject.TryGetProperty("frameworks", out var frameworks) ||
            !frameworks.TryGetProperty(project.GetPropertyValue("TargetFramework"), out var framework))
            throw new ExportException("stale-restore", "restored project framework metadata missing: " + project.FullPath);
        if (framework.TryGetProperty("dependencies", out var dependencies))
            foreach (var dependency in dependencies.EnumerateObject())
                if (dependency.Value.TryGetProperty("target", out var target) && target.GetString() == "Package")
                    restored.Add(dependency.Name, dependency.Value);
        var ids = references.Select(reference => reference.EvaluatedInclude).ToArray();
        if (ids.Distinct(StringComparer.OrdinalIgnoreCase).Count() != ids.Length)
            throw new ExportException("unsupported-package", "duplicate evaluated PackageReference");
        if (!ids.ToHashSet(StringComparer.OrdinalIgnoreCase).SetEquals(restored.Keys))
            throw new ExportException("stale-restore", "evaluated direct package set differs from restore: " + project.FullPath);
        var libraries = assets.GetProperty("libraries").EnumerateObject()
            .Where(library => library.Value.GetProperty("type").GetString() == "package")
            .Select(library => library.Name).ToHashSet(StringComparer.OrdinalIgnoreCase);
        foreach (var reference in references)
        {
            var version = reference.GetMetadataValue("Version");
            if (!version.StartsWith('[') || !version.EndsWith(']') || version.Contains(','))
                throw new ExportException("unsupported-package", "exact inline version required: " + reference.EvaluatedInclude);
            var selected = version[1..^1];
            var dependency = restored[reference.EvaluatedInclude];
            var range = dependency.GetProperty("version").GetString()!.Replace(" ", "", StringComparison.Ordinal);
            if (!libraries.Contains(reference.EvaluatedInclude + "/" + selected) ||
                (range != version && range != "[" + selected + "," + selected + "]"))
                throw new ExportException("stale-restore", "package reference differs from restored version: " + reference.EvaluatedInclude);
            var currentPrivacy = Privacy(reference.GetMetadataValue("PrivateAssets"), "unsupported-package");
            var savedPrivacy = Privacy(dependency.TryGetProperty("suppressParent", out var privacy) ? privacy.GetString()! : "", "stale-restore");
            if (currentPrivacy != savedPrivacy)
                throw new ExportException("stale-restore", "PrivateAssets differs from restore: " + reference.EvaluatedInclude);
            foreach (var (name, allowed) in new[] { ("IncludeAssets", "all"), ("ExcludeAssets", "none") })
            {
                var value = reference.GetMetadataValue(name);
                if (value.Length != 0 && !value.Equals(allowed, StringComparison.OrdinalIgnoreCase))
                    throw new ExportException("unsupported-package", "nondefault " + name + " is outside the managed package slice");
                var restoredName = name == "IncludeAssets" ? "include" : "exclude";
                if (dependency.TryGetProperty(restoredName, out var saved) &&
                    !string.Equals(saved.GetString(), allowed, StringComparison.OrdinalIgnoreCase))
                    throw new ExportException("stale-restore", name + " differs from restore: " + reference.EvaluatedInclude);
            }
        }
    }

    private static string Privacy(string value, string error)
    {
        var flags = value.Split([';', ','], StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (flags.Count == 0 || flags.SetEquals(["contentfiles", "analyzers", "build"])) return "default";
        if (flags.SetEquals(["all"])) return "all";
        if (flags.SetEquals(["none"])) return "none";
        throw new ExportException(error, "PrivateAssets must be default, all or none");
    }
}
