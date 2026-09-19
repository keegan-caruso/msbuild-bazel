using System.Text.Json;
using Microsoft.Build.Execution;
using Microsoft.Build.Graph;
using NuGet.Versioning;

internal static class PackageRestoreValidation
{
    public static void Validate(ProjectInstance project, JsonElement assets)
    {
        if (!assets.TryGetProperty("project", out var restoreProject) ||
            !restoreProject.TryGetProperty("frameworks", out var frameworks) ||
            !frameworks.TryGetProperty(project.GetPropertyValue("TargetFramework"), out var framework))
            throw new ExportException("stale-restore", "restored project framework metadata missing: " + project.FullPath);
        ValidateCentralSettings(project, restoreProject);
        var selected = assets.GetProperty("targets").GetProperty(project.GetPropertyValue("TargetFramework"));
        var libraries = assets.GetProperty("libraries").EnumerateObject()
            .Where(library => library.Value.GetProperty("type").GetString() == "package" && selected.TryGetProperty(library.Name, out _))
            .Select(library => library.Name).ToHashSet(StringComparer.OrdinalIgnoreCase);
        ValidateRequested(project, framework, libraries);
    }

    internal static void ValidateSuccessfulRestore(ProjectInstance owner, string assetsPath)
    {
        var cachePath = Path.Combine(Path.GetDirectoryName(assetsPath)!, "project.nuget.cache");
        if (!File.Exists(cachePath))
            throw new ExportException("stale-restore", "successful restore marker missing: " + owner.FullPath);
        using (var cache = JsonDocument.Parse(File.ReadAllText(cachePath)))
            if (!cache.RootElement.TryGetProperty("success", out var success) || success.ValueKind != JsonValueKind.True)
                throw new ExportException("stale-restore", "latest restore did not succeed: " + owner.FullPath);
    }

    // A consumer's dependency spec is a snapshot taken when that consumer was
    // restored. Checking only each project's own assets misses partial restores.
    public static void ValidateGraph(IEnumerable<ProjectGraphNode> nodes)
    {
        foreach (var consumer in nodes)
        {
            var closure = new HashSet<ProjectGraphNode>();
            var pending = new Stack<ProjectGraphNode>();
            pending.Push(consumer);
            while (pending.TryPop(out var currentNode))
            {
                if (!closure.Add(currentNode)) continue;
                // NuGet excludes ReferenceOutputAssembly=false edges from the
                // consumer restore snapshot, even though MSBuild still schedules
                // their producers. Each producer validates its own snapshot below.
                var references = currentNode.ProjectInstance.GetItems("ProjectReference");
                var pathComparer = OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;
                var restoredPaths = references
                    .Where(IsRestoreReference)
                    .Select(reference => CanonicalProjectPath(Path.GetFullPath(reference.EvaluatedInclude,
                        Path.GetDirectoryName(currentNode.ProjectInstance.FullPath)!)))
                    .ToHashSet(pathComparer);
                foreach (var dependency in currentNode.ProjectReferences)
                    if (restoredPaths.Contains(CanonicalProjectPath(dependency.ProjectInstance.FullPath)))
                        pending.Push(dependency);
            }
            var projects = closure.Select(node => node.ProjectInstance)
                .Where(project => project.FullPath.EndsWith(".csproj", StringComparison.OrdinalIgnoreCase)).ToArray();
            foreach (var samePath in projects.GroupBy(project => (Path: CanonicalProjectPath(project.FullPath), Framework: project.GetPropertyValue("TargetFramework"))))
                if (samePath.Select(RequestedSignature).Distinct(StringComparer.Ordinal).Count() > 1)
                    throw new ExportException("unsupported-configured-restore",
                        "path-keyed restore specs cannot distinguish configured package requests: " + samePath.Key);
            var owner = consumer.ProjectInstance;
            var assetsPath = owner.GetPropertyValue("ProjectAssetsFile");
            if (string.IsNullOrWhiteSpace(assetsPath))
                assetsPath = Path.Combine(Path.GetDirectoryName(owner.FullPath)!, "obj", "project.assets.json");
            assetsPath = Path.GetFullPath(assetsPath, Path.GetDirectoryName(owner.FullPath)!);
            ValidateSuccessfulRestore(owner, assetsPath);
            var specPath = Path.Combine(Path.GetDirectoryName(assetsPath)!, Path.GetFileName(owner.FullPath) + ".nuget.dgspec.json");
            if (!File.Exists(specPath))
                throw new ExportException("stale-restore", "consumer dependency restore snapshot missing: " + owner.FullPath);
            using var document = JsonDocument.Parse(File.ReadAllText(specPath));
            if (!document.RootElement.TryGetProperty("projects", out var savedProjects))
                throw new ExportException("stale-restore", "consumer dependency restore snapshot incomplete: " + owner.FullPath);
            var specs = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
            foreach (var spec in savedProjects.EnumerateObject())
                if (!specs.TryAdd(CanonicalProjectPath(spec.Name), spec.Value))
                    throw new ExportException("stale-restore", "duplicate canonical project in restore snapshot: " + owner.FullPath);
            foreach (var project in projects)
            {
                if (!specs.TryGetValue(CanonicalProjectPath(project.FullPath), out var saved) ||
                    !saved.TryGetProperty("frameworks", out var frameworks) ||
                    !frameworks.TryGetProperty(project.GetPropertyValue("TargetFramework"), out var framework))
                    throw new ExportException("stale-restore",
                        "consumer restore snapshot lacks configured dependency: " + owner.FullPath + " -> " + project.FullPath);
                // Compare requested constraints, never resolved transitive versions:
                // NuGet can legitimately resolve a different version in a consumer.
                ValidateCentralSettings(project, saved);
                ValidateProjectReferences(project, saved);
                ValidateRequested(project, framework, null);
            }
        }
    }

    private static void ValidateProjectReferences(ProjectInstance project, JsonElement saved)
    {
        if (!saved.TryGetProperty("restore", out var restore) ||
            !restore.TryGetProperty("frameworks", out var frameworks) ||
            !frameworks.TryGetProperty(project.GetPropertyValue("TargetFramework"), out var framework) ||
            !framework.TryGetProperty("projectReferences", out var restoredReferences))
            throw new ExportException("stale-restore", "restored direct project references missing: " + project.FullPath);
        var current = new HashSet<string>(StringComparer.Ordinal);
        // Evaluated items are the direct declarations, unlike ProjectGraph edges
        // which can include SDK-inferred transitive references.
        foreach (var reference in project.GetItems("ProjectReference"))
        {
            if (NerdbankProject.IsReference(reference)) continue;
            var privateAssets = reference.GetMetadataValue("PrivateAssets").ToLowerInvariant();
            if (privateAssets.Length != 0 && (!reference.GetMetadataValue("ReferenceOutputAssembly").Equals("false", StringComparison.OrdinalIgnoreCase) || (privateAssets != "all" && privateAssets != "contentfiles;build")))
                throw new ExportException("unsupported-project-reference-restore", "unsupported PrivateAssets: " + project.FullPath);
            foreach (var metadata in new[] { "IncludeAssets", "ExcludeAssets" })
                if (!string.IsNullOrEmpty(reference.GetMetadataValue(metadata)))
                    throw new ExportException("unsupported-project-reference-restore", "nondefault " + metadata + ": " + project.FullPath);
            if (IsRestoreReference(reference))
                current.Add(CanonicalProjectPath(Path.GetFullPath(reference.EvaluatedInclude, Path.GetDirectoryName(project.FullPath)!)));
        }
        var restored = new HashSet<string>(StringComparer.Ordinal);
        foreach (var reference in restoredReferences.EnumerateObject())
        {
            if (reference.Value.EnumerateObject().Any(property => property.Name != "projectPath"))
                throw new ExportException("stale-restore", "unsupported saved project-reference metadata: " + project.FullPath);
            var path = CanonicalProjectPath(Path.GetFullPath(reference.Name, Path.GetDirectoryName(project.FullPath)!));
            if (!reference.Value.TryGetProperty("projectPath", out var recordedPath) ||
                CanonicalProjectPath(Path.GetFullPath(recordedPath.GetString()!, Path.GetDirectoryName(project.FullPath)!)) != path)
                throw new ExportException("stale-restore", "saved project-reference identity differs: " + project.FullPath);
            restored.Add(path);
        }
        if (!current.SetEquals(restored))
            throw new ExportException("stale-restore", "direct project reference set differs from restore: " + project.FullPath);
    }

    private static bool IsRestoreReference(ProjectItemInstance reference)
    {
        if (NerdbankProject.IsReference(reference)) return false;
        var output = reference.GetMetadataValue("ReferenceOutputAssembly");
        var ordinary = output.Length == 0 || output.Equals("true", StringComparison.OrdinalIgnoreCase);
        if (!ordinary && !output.Equals("false", StringComparison.OrdinalIgnoreCase))
            throw new ExportException("unsupported-project-reference-role", "ReferenceOutputAssembly must be true or false");
        var itemType = reference.GetMetadataValue("OutputItemType");
        if (itemType.Length != 0 && (ordinary || !itemType.Equals("Analyzer", StringComparison.OrdinalIgnoreCase) && !itemType.Equals("None", StringComparison.OrdinalIgnoreCase)))
            throw new ExportException("unsupported-project-reference-role", "only Analyzer with ReferenceOutputAssembly=false is qualified");
        var build = reference.GetMetadataValue("BuildReference");
        if ((build.Length != 0 && !build.Equals("true", StringComparison.OrdinalIgnoreCase)) ||
            reference.GetMetadataValue("Targets").Length != 0)
            throw new ExportException("unsupported-project-reference-role", "disabled or custom-target project references are outside the Build slice");
        return ordinary;
    }

    private static string CanonicalProjectPath(string path)
    {
        var full = Path.GetFullPath(path);
        var file = new FileInfo(Path.Combine(GraphExporter.CanonicalDirectory(Path.GetDirectoryName(full)!), Path.GetFileName(full)));
        return file.Exists ? file.ResolveLinkTarget(true)?.FullName ?? file.FullName : file.FullName;
    }

    private static bool Central(ProjectInstance project) => project.GetPropertyValue("ManagePackageVersionsCentrally").Equals("true", StringComparison.OrdinalIgnoreCase);

    private static SortedDictionary<string, string> CentralVersions(ProjectInstance project)
    {
        var result = new SortedDictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var item in project.GetItems("PackageVersion"))
        {
            var version = item.GetMetadataValue("Version");
            if (!VersionRange.TryParse(version, out var range) || range.IsFloating || !result.TryAdd(item.EvaluatedInclude, range.ToNormalizedString()))
                throw new ExportException("unsupported-package", "central package versions must be unique nonfloating ranges: " + item.EvaluatedInclude);
        }
        return result;
    }

    private static void ValidateCentralSettings(ProjectInstance project, JsonElement saved)
    {
        var central = Central(project);
        var pinning = central && project.GetPropertyValue("CentralPackageTransitivePinningEnabled").Equals("true", StringComparison.OrdinalIgnoreCase);
        var restore = saved.GetProperty("restore");
        bool Enabled(string name) => restore.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;
        if (central != Enabled("centralPackageVersionsManagementEnabled") || pinning != Enabled("CentralPackageTransitivePinningEnabled"))
            throw new ExportException("stale-restore", "central package policy differs from restore: " + project.FullPath);
        if (!central) return;
        var current = CentralVersions(project);
        var framework = saved.GetProperty("frameworks").GetProperty(project.GetPropertyValue("TargetFramework"));
        var restored = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (framework.TryGetProperty("centralPackageVersions", out var versions))
            foreach (var item in versions.EnumerateObject())
            {
                if (!VersionRange.TryParse(item.Value.GetString() ?? "", out var range) || range.IsFloating || !restored.TryAdd(item.Name, range.ToNormalizedString()))
                    throw new ExportException("stale-restore", "invalid restored central package version: " + item.Name);
            }
        if (current.Count != restored.Count || current.Any(pair => !restored.TryGetValue(pair.Key, out var version) || version != pair.Value))
            throw new ExportException("stale-restore", "central package versions differ from restore: " + project.FullPath);
    }

    private static string RequestedSignature(ProjectInstance project) => JsonSerializer.Serialize(new
    {
        Central = Central(project),
        Pinning = project.GetPropertyValue("CentralPackageTransitivePinningEnabled").ToLowerInvariant(),
        Versions = Central(project) ? CentralVersions(project) : null,
        References = project.GetItems("PackageReference").OrderBy(item => item.EvaluatedInclude, StringComparer.OrdinalIgnoreCase)
            .Select(item => new[] { item.EvaluatedInclude.ToLowerInvariant(), RequestedVersion(project, item).ToLowerInvariant(),
                Privacy(item.GetMetadataValue("PrivateAssets"), "unsupported-package") })
    });

    private static string RequestedVersion(ProjectInstance project, ProjectItemInstance reference)
    {
        var version = reference.GetMetadataValue("Version");
        var central = project.GetPropertyValue("ManagePackageVersionsCentrally").Equals("true", StringComparison.OrdinalIgnoreCase);
        if (!central) return version;
        if (reference.GetMetadataValue("VersionOverride").Length != 0)
            throw new ExportException("unsupported-package", "central version overrides are outside the qualified slice");
        // SDK implicit references keep their framework-supplied version.
        if (reference.GetMetadataValue("IsImplicitlyDefined").Equals("true", StringComparison.OrdinalIgnoreCase)) return version;
        if (version.Length != 0)
            throw new ExportException("unsupported-package", "inline version with central package management");
        var versions = project.GetItems("PackageVersion").Where(item =>
            item.EvaluatedInclude.Equals(reference.EvaluatedInclude, StringComparison.OrdinalIgnoreCase)).ToArray();
        if (versions.Length != 1)
            throw new ExportException("unsupported-package", "central package version must be unambiguous: " + reference.EvaluatedInclude);
        return versions[0].GetMetadataValue("Version");
    }

    private static void ValidateRequested(ProjectInstance project, JsonElement framework, HashSet<string>? libraries)
    {
        if (libraries is not null && Central(project) && project.GetPropertyValue("CentralPackageTransitivePinningEnabled").Equals("true", StringComparison.OrdinalIgnoreCase))
        {
            foreach (var (id, version) in CentralVersions(project))
            {
                var range = VersionRange.Parse(version);
                foreach (var library in libraries.Where(library => library.StartsWith(id + "/", StringComparison.OrdinalIgnoreCase)))
                    if (!NuGetVersion.TryParse(library[(library.IndexOf('/') + 1)..], out var resolved) || !range.Satisfies(resolved))
                        throw new ExportException("stale-restore", "resolved package violates central pin: " + id);
            }
        }
        var references = project.GetItems("PackageReference").ToArray();
        var restored = new Dictionary<string, JsonElement>(StringComparer.OrdinalIgnoreCase);
        if (framework.TryGetProperty("dependencies", out var dependencies))
            foreach (var dependency in dependencies.EnumerateObject())
                if (dependency.Value.TryGetProperty("target", out var target) && target.GetString() == "Package")
                    restored.Add(dependency.Name, dependency.Value);
        var ids = references.Select(reference => reference.EvaluatedInclude).ToArray();
        if (ids.Distinct(StringComparer.OrdinalIgnoreCase).Count() != ids.Length)
            throw new ExportException("unsupported-package", "duplicate evaluated PackageReference");
        if (!ids.ToHashSet(StringComparer.OrdinalIgnoreCase).SetEquals(restored.Keys))
            throw new ExportException("stale-restore", "evaluated direct package set differs from restore: " + project.FullPath);
        foreach (var reference in references)
        {
            var version = RequestedVersion(project, reference);
            var selected = PilotPackagePolicy.SelectedVersion(reference.EvaluatedInclude,
                NuGetVersion.TryParse(version, out var normalizedRequested) ? normalizedRequested.ToNormalizedString() : version);
            var central = Central(project);
            var frameworkFloat = project.GetPropertyValue("TargetFramework") == "netstandard2.0" &&
                reference.EvaluatedInclude.Equals("NETStandard.Library", StringComparison.OrdinalIgnoreCase) &&
                reference.GetMetadataValue("IsImplicitlyDefined").Equals("true", StringComparison.OrdinalIgnoreCase) && version == "2.0.0-*";
            if (frameworkFloat) selected = "2.0.0";
            if (!VersionRange.TryParse(version, out var requestedRange) || requestedRange.IsFloating && !frameworkFloat ||
                !central && (selected is null || !NuGetVersion.TryParse(selected, out _)))
                throw new ExportException("unsupported-package", "exact inline version or qualified pilot version required: " + reference.EvaluatedInclude);
            var dependency = restored[reference.EvaluatedInclude];
            var savedVersion = dependency.GetProperty("version").GetString()!;
            if (frameworkFloat && (!dependency.TryGetProperty("autoReferenced", out var implicitReference) || implicitReference.ValueKind != JsonValueKind.True))
                throw new ExportException("stale-restore", "implicit framework package differs from restore");
            if (!VersionRange.TryParse(savedVersion, out var restoredRange) || !requestedRange.Equals(restoredRange) ||
                (libraries is not null && (central && !frameworkFloat
                    ? !libraries.Any(library => library.StartsWith(reference.EvaluatedInclude + "/", StringComparison.OrdinalIgnoreCase) &&
                        NuGetVersion.TryParse(library[(library.IndexOf('/') + 1)..], out var resolved) && requestedRange.Satisfies(resolved))
                    : !libraries.Contains(reference.EvaluatedInclude + "/" + NuGetVersion.Parse(selected!).ToNormalizedString()))))
                throw new ExportException("stale-restore", "package reference differs from restored version: " + reference.EvaluatedInclude);
            var currentPrivacy = Privacy(reference.GetMetadataValue("PrivateAssets"), "unsupported-package");
            var savedPrivacy = Privacy(dependency.TryGetProperty("suppressParent", out var privacy) ? privacy.GetString()! : "", "stale-restore");
            if (currentPrivacy != savedPrivacy)
                throw new ExportException("stale-restore", "PrivateAssets differs from restore: " + reference.EvaluatedInclude);
            foreach (var (name, allowed) in new[] { ("IncludeAssets", "all"), ("ExcludeAssets", "none") })
            {
                var value = AssetFlags(reference.GetMetadataValue(name), allowed);
                var globalReference = name == "IncludeAssets" && value == "analyzers;build;contentfiles;native;runtime" && currentPrivacy == "all" &&
                    project.GetItems("GlobalPackageReference").Count(item => item.EvaluatedInclude.Equals(reference.EvaluatedInclude, StringComparison.OrdinalIgnoreCase)) == 1;
                if (value != allowed && !(name == "IncludeAssets" && value == "analyzers;build") && !globalReference)
                    throw new ExportException("unsupported-package", "nondefault " + name + " is outside the managed package slice");
                var restoredName = name == "IncludeAssets" ? "include" : "exclude";
                var restoredFlags = dependency.TryGetProperty(restoredName, out var saved) ? AssetFlags(saved.GetString()!, allowed) : allowed;
                if (restoredFlags != value)
                    throw new ExportException("stale-restore", name + " differs from restore: " + reference.EvaluatedInclude);
            }
        }
    }

    private static string AssetFlags(string value, string fallback) => string.IsNullOrWhiteSpace(value) ? fallback :
        string.Join(";", value.Split([';', ','], StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
            .Select(flag => flag.ToLowerInvariant()).Distinct().Order(StringComparer.Ordinal));

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
