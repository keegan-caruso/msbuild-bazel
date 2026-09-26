using System.Xml.Linq;
using Microsoft.Build.Execution;

// Exact authored assembly-to-project bindings. No assembly-name discovery.
internal static class ReferenceProjects
{
    internal static void Inject(Request request, XElement root)
    {
        var group = new XElement("ItemGroup");
        foreach (var (name, project) in request.ReferenceProjects ?? [])
        {
            if (name.Length == 0 || name.Any(c => !char.IsAsciiLetterOrDigit(c) && c is not ('.' or '-' or '_')))
            {
                throw new InvalidDataException("Invalid reference project identity: " + name);
            }
            group.Add(new XElement("_BazelBoundProjectReference", new XAttribute("Include", "@(Reference->WithMetadataValue('Identity', '" + name + "'))")));
            var relative = Path.GetRelativePath(Path.GetDirectoryName(Program.Safe(request.Project.Path))!, Program.Safe(project));
            group.Add(new XElement("ProjectReference", new XAttribute("Include", Program.Escape(relative)), new XAttribute("Condition", "'@(Reference->WithMetadataValue('Identity', '" + name + "'))' != ''")));
            group.Add(new XElement("Reference", new XAttribute("Remove", name)));
        }
        root.Add(group);
    }

    internal static void Validate(Request request, ProjectInstance evaluated)
    {
        foreach (var name in (request.ReferenceProjects ?? []).Keys)
        {
            var items = evaluated.GetItems("_BazelBoundProjectReference").Where(i => i.EvaluatedInclude == name).ToArray();
            if (items.Length != 1 || items[0].Metadata.Any(m => m.Name is "HintPath" or "Aliases" or "SpecificVersion" or "EmbedInteropTypes" or "PrivateAssets"))
            {
                throw new InvalidDataException("Reference project binding requires one plain matching Reference: " + name);
            }
        }
    }
}
