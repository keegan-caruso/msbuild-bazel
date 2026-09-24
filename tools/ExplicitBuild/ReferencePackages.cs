using System.Xml.Linq;
using Microsoft.Build.Execution;

// An explicit same-identity Reference-to-package binding, never a resolver.
internal static class ReferencePackages
{
    internal static void Inject(Request request, XElement root)
    {
        var group = new XElement("ItemGroup");
        foreach (var id in request.ReferencePackages ?? [])
        {
            if (id.Any(c => !char.IsAsciiLetterOrDigit(c) && c is not ('.' or '-' or '_')))
            {
                throw new InvalidDataException("Invalid reference package identity");
            }

            group.Add(new XElement("_BazelBoundPackageReference", new XAttribute("Include", "@(Reference->WithMetadataValue('Identity', '" + id + "'))")));
        }
        group.Add(new XElement("PackageReference", new XAttribute("Include", "@(_BazelBoundPackageReference)"), new XElement("IsImplicitlyDefined", "true")));
        group.Add(new XElement("Reference", new XAttribute("Remove", "@(_BazelBoundPackageReference)")));
        root.Add(group);
    }
    internal static void Validate(Request request, ProjectInstance evaluated)
    {
        var rows = evaluated.GetItems("_BazelBoundPackageReference");
        foreach (var id in request.ReferencePackages ?? [])
        {
            var matches = rows.Where(i => i.EvaluatedInclude.Equals(id, StringComparison.OrdinalIgnoreCase)).ToArray();
            if (matches.Length != 1)
            {
                throw new InvalidDataException("Reference package binding requires exactly one matching Reference: " + id);
            }

            foreach (var name in new[] { "HintPath", "Aliases", "SpecificVersion", "EmbedInteropTypes", "ProjectPath" })
            {
                if (matches[0].GetMetadataValue(name).Length > 0)
                {
                    throw new InvalidDataException("Unsupported bound Reference metadata: " + name);
                }
            }
        }
    }
}
