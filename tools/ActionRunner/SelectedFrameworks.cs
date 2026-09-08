using System.Xml.Linq;

namespace ActionRunner;

// Reproduce exported SDK reference negotiation at the late SDK evaluation boundary.
internal static class SelectedFrameworks
{
    public static GraphFrameworkSelection? ForProject(ActionRequest request, string project)
    {
        var framework = request.GraphGlobalProperties?.GetValueOrDefault("targetframework");
        return request.GraphFrameworkSelections?.Where(pair => (pair.Value.Project ?? pair.Key) == project &&
            (framework is null || pair.Value.TargetFramework == framework)).Select(pair => pair.Value).SingleOrDefault();
    }

    public static string? Stage(ActionRequest request, Workspace workspace)
    {
        if (request.GraphFrameworkSelections is not { Count: > 0 } selections) return null;
        if (ForProject(request, request.GraphProject!) is null)
            throw new InvalidDataException("selected framework entry missing");
        var document = new XElement("Project");
        foreach (var (key, selection) in selections.OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            var project = selection.Project ?? key;
            if (!Files.ValidRelativePath(project) || !project.EndsWith(".csproj", StringComparison.Ordinal) || selection.TargetFramework is not ("net10.0" or "net8.0" or "netstandard2.0"))
                throw new InvalidDataException("selected framework project invalid");
            var fullPath = Path.Combine(workspace.Root, project);
            var condition = "'$(MSBuildProjectFullPath)' == '" + Escape(fullPath) + "' and '$(TargetFramework)' == '" + selection.TargetFramework + "'";
            document.Add(new XElement("PropertyGroup", new XAttribute("Condition", condition),
                new XElement("InnerBuildProperty", ""), new XElement("InnerBuildPropertyValues", "")));
            var items = new XElement("ItemGroup", new XAttribute("Condition", condition));
            foreach (var (reference, framework) in selection.References.OrderBy(pair => pair.Key, StringComparer.Ordinal))
            {
                if (!selections.Any(pair => (pair.Value.Project ?? pair.Key) == reference && pair.Value.TargetFramework == framework))
                    throw new InvalidDataException("selected framework dependency invalid");
                items.Add(new XElement("ProjectReference", new XAttribute("Update", Escape(Path.GetRelativePath(Path.GetDirectoryName(fullPath)!, Path.Combine(workspace.Root, reference)))),
                    new XElement("SetTargetFramework", "TargetFramework=" + framework)));
            }
            // Single-target producers were exported without a TargetFramework
            // global. Recreate that exact graph identity before static graph
            // expansion, rather than inheriting an explicit consumer framework.
            foreach (var (referenceKey, dependency) in selections.Where(pair => pair.Value.RemoveFrameworkGlobal))
            {
                var reference = dependency.Project ?? referenceKey;
                items.Add(new XElement("ProjectReference", new XAttribute("Update", Escape(Path.GetRelativePath(Path.GetDirectoryName(fullPath)!, Path.Combine(workspace.Root, reference)))),
                    new XElement("GlobalPropertiesToRemove", "%(ProjectReference.GlobalPropertiesToRemove);TargetFramework")));
            }
            document.Add(items);
        }
        // Restore can add transitive references after evaluation. Their SDK-selected
        // inner identity must match the declared closure identity.
        // Carry that selection onto those existing items before framework negotiation;
        // no reference is added, removed, or compiled outside the exported graph.
        foreach (var (key, selection) in selections)
        {
            var project = selection.Project ?? key;
            var runtimeItems = new XElement("ItemGroup");
            var references = selections.GroupBy(pair => pair.Value.Project ?? pair.Key)
                .Where(group => group.Select(pair => pair.Value.TargetFramework).Distinct().Count() == 1)
                .ToDictionary(group => group.Key, group => group.First().Value.TargetFramework);
            foreach (var reference in selection.References) references[reference.Key] = reference.Value;
            foreach (var dependency in references)
            {
                runtimeItems.Add(new XElement("_MSBuildProjectReferenceExistent",
                    new XAttribute("Condition", "'%(_MSBuildProjectReferenceExistent.FullPath)' == '" + Escape(Path.Combine(workspace.Root, dependency.Key)) + "'"),
                    new XElement("SetTargetFramework", "TargetFramework=" + dependency.Value)));
            }
            document.Add(new XElement("Target", new XAttribute("Name", "BazelApplySelectedReferenceFrameworks" + document.Elements("Target").Count()),
                new XAttribute("BeforeTargets", "_GetProjectReferenceTargetFrameworkProperties"),
                new XAttribute("Condition", "'$(MSBuildProjectFullPath)' == '" + Escape(Path.Combine(workspace.Root, project)) + "' and '$(TargetFramework)' == '" + selection.TargetFramework + "'"), runtimeItems));
        }
        var path = Path.Combine(workspace.Scratch, "selected-frameworks.targets");
        new XDocument(document).Save(path);
        return path;
    }

    private static string Escape(string value) => value.Replace("%", "%25").Replace("'", "%27");
}
