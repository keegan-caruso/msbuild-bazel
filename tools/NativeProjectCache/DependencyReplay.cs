using System.Xml.Linq;

// Only private dependency project copies are replaced. Their recorded SDK
// outputs are supplied by Bazel; no imports, compiler or child builds run here.
internal static class DependencyReplay
{
    internal static void Write(string path, Results results, string workspace)
    {
        string Expand(string value) => value.Replace("${WORKSPACE}", workspace, StringComparison.Ordinal)
            .Replace("$", "%24", StringComparison.Ordinal).Replace("@", "%40", StringComparison.Ordinal);
        var document = new XElement("Project", new XAttribute("DefaultTargets", "Build"));
        var index = 0;
        foreach (var (name, items) in results.Targets.OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            var itemName = "_Recorded" + index++;
            var target = new XElement("Target", new XAttribute("Name", name), new XAttribute("Returns", "@(" + itemName + ")"), new XAttribute("KeepDuplicateOutputs", "true"));
            var group = new XElement("ItemGroup");
            foreach (var item in items)
                group.Add(new XElement(itemName, new XAttribute("Include", Expand(item.Spec)),
                    item.Metadata.Select(pair => new XElement(pair.Key, Expand(pair.Value)))));
            target.Add(group); document.Add(target);
        }
        if (File.Exists(path) && !OperatingSystem.IsWindows()) File.SetUnixFileMode(path, File.GetUnixFileMode(path) | UnixFileMode.UserWrite);
        new XDocument(document).Save(path);
    }
}
