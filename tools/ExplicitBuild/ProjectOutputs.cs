using System.Xml;
using System.Xml.Linq;
using Microsoft.Build.Execution;

internal sealed record ProjectOutput(string Project, string Assembly, string? Directory, string Type, Dictionary<string, string> Metadata, string? File = null);

internal static class ProjectOutputs
{
    private static string Relative(ProjectOutput output, int index) => Path.Combine(".project-outputs", index.ToString(System.Globalization.CultureInfo.InvariantCulture), Program.Safe(output.Assembly));
    internal static void Stage(Request request, string workspace)
    {
        var outputs = request.ProjectOutputs ?? [];
        for (var i = 0; i < outputs.Length; i++)
        {
            var output = outputs[i];
            Program.Safe(output.Project);
            XmlConvert.VerifyNCName(output.Type);
            if (output.Type.StartsWith("_Bazel", StringComparison.OrdinalIgnoreCase) || new[] { "Compile", "ProjectReference", "Reference", "Analyzer", "PackageReference", "PackageVersion", "FrameworkReference" }.Contains(output.Type, StringComparer.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Project output items cannot replace dependency/source declarations");
            }

            if (output.Assembly.Contains('/') || (output.File is null) == (output.Directory is null))
            {
                throw new InvalidDataException("Unsupported project output item");
            }

            var destination = Path.Combine(workspace, Relative(output, i));
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            File.Copy(output.File ?? Path.Combine(output.Directory!, output.Assembly), destination);
        }
    }
    internal static void Inject(Request request, XElement items, string workspace, Func<string, string> compilerPath)
    {
        var outputs = request.ProjectOutputs ?? [];
        for (var i = 0; i < outputs.Length; i++)
        {
            var output = outputs[i];
            var item = new XElement(output.Type, new XAttribute("Include", Program.Escape(compilerPath(Path.Combine(workspace, Relative(output, i))))), new XElement("Link", Program.Escape(output.Assembly)));
            foreach (var (name, value) in output.Metadata)
            {
                XmlConvert.VerifyNCName(name);
                if (name is not ("CopyToOutputDirectory" or "CopyToPublishDirectory"))
                {
                    throw new InvalidDataException("Unsupported project output metadata: " + name);
                }

                if (value is not ("Never" or "Always" or "PreserveNewest" or "IfDifferent"))
                {
                    throw new InvalidDataException("Unsupported project output copy mode");
                }

                item.Add(new XElement(name, value));
            }
            items.Add(item);
        }
    }
    internal static void Validate(ProjectOutput output, ProjectItemInstance original)
    {
        if (original.GetMetadataValue("OutputItemType") != output.Type || !original.GetMetadataValue("ReferenceOutputAssembly").Equals("false", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Project output role disagrees with Bazel declaration");
        }

        foreach (var name in new[] { "CopyToOutputDirectory", "CopyToPublishDirectory" })
        {
            if (original.GetMetadataValue(name) != output.Metadata.GetValueOrDefault(name, ""))
            {
                throw new InvalidDataException("Project output metadata disagrees with Bazel declaration: " + name);
            }
        }

        foreach (var name in new[] { "Link", "TargetPath" })
        {
            if (original.GetMetadataValue(name).Length > 0)
            {
                throw new InvalidDataException("Unsupported project output metadata: " + name);
            }
        }
    }
}
