using System.Xml.Linq;

namespace ActionRunner;

// Reproduce exported SDK reference negotiation at the late SDK evaluation boundary.
internal static class SelectedFrameworks
{
    public static string? Stage(ActionRequest request, Workspace workspace)
    {
        if (request.GraphFrameworkSelections is not { Count: > 0 } selections) return null;
        if (!selections.ContainsKey(request.GraphProject!))
            throw new InvalidDataException("selected framework entry missing");
        var document = new XElement("Project");
        foreach (var (project, selection) in selections.OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            if (!Files.ValidRelativePath(project) || !project.EndsWith(".csproj", StringComparison.Ordinal) || selection.TargetFramework is not ("net10.0" or "netstandard2.0"))
                throw new InvalidDataException("selected framework project invalid");
            var fullPath = Path.Combine(workspace.Root, project);
            var condition = "'$(MSBuildProjectFullPath)' == '" + Escape(fullPath) + "' and '$(TargetFramework)' == '" + selection.TargetFramework + "'";
            document.Add(new XElement("PropertyGroup", new XAttribute("Condition", condition),
                new XElement("InnerBuildProperty", ""), new XElement("InnerBuildPropertyValues", "")));
            var items = new XElement("ItemGroup", new XAttribute("Condition", condition));
            foreach (var (reference, framework) in selection.References.OrderBy(pair => pair.Key, StringComparer.Ordinal))
            {
                if (!selections.TryGetValue(reference, out var dependency) || framework != dependency.TargetFramework)
                    throw new InvalidDataException("selected framework dependency invalid");
                items.Add(new XElement("ProjectReference", new XAttribute("Update", Escape(Path.GetRelativePath(Path.GetDirectoryName(fullPath)!, Path.Combine(workspace.Root, reference)))),
                    new XElement("SetTargetFramework", "TargetFramework=" + framework)));
            }
            document.Add(items);
        }
        // Restore can add transitive references after evaluation. Their SDK-selected
        // inner identity must match the declared closure identity.
        // Carry that selection onto those existing items before framework negotiation;
        // no reference is added, removed, or compiled outside the exported graph.
        var selectedDependencies = selections.Values.SelectMany(selection => selection.References)
            .GroupBy(pair => pair.Key, StringComparer.Ordinal);
        var runtimeItems = new XElement("ItemGroup");
        foreach (var dependency in selectedDependencies)
        {
            var framework = dependency.Select(pair => pair.Value).Distinct(StringComparer.Ordinal).Single();
            runtimeItems.Add(new XElement("_MSBuildProjectReferenceExistent",
                new XAttribute("Condition", "'%(_MSBuildProjectReferenceExistent.FullPath)' == '" + Escape(Path.Combine(workspace.Root, dependency.Key)) + "'"),
                new XElement("SetTargetFramework", "TargetFramework=" + framework)));
        }
        document.Add(new XElement("Target", new XAttribute("Name", "BazelApplySelectedReferenceFrameworks"),
            new XAttribute("BeforeTargets", "_GetProjectReferenceTargetFrameworkProperties"),
            new XAttribute("Condition", "'$(TargetFramework)' == 'net10.0' or '$(TargetFramework)' == 'netstandard2.0'"), runtimeItems));
        var path = Path.Combine(workspace.Scratch, "selected-frameworks.targets");
        new XDocument(document).Save(path);
        return path;
    }

    private static string Escape(string value) => value.Replace("%", "%25").Replace("'", "%27");
}
