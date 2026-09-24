using System.Xml;
using Microsoft.Build.Execution;

internal sealed record BuildTool(string Project, string EntryPoint, string[] Directories, Input[] Data, PackageInput[]? Packages = null, bool Native = false, string LayoutPrefix = "");
internal sealed record FileBinding(string Property, int Tool);

internal static class BuildTools
{
    private static string DirectoryPath(string workspace, int index) => Path.Combine(workspace, ".build-tools", index.ToString(System.Globalization.CultureInfo.InvariantCulture));
    internal static void Stage(Request request, string workspace)
    {
        var tools = request.BuildTools ?? [];
        for (var i = 0; i < tools.Length; i++)
        {
            var tool = tools[i];
            Program.Safe(tool.Project);
            var root = DirectoryPath(workspace, i);
            var destination = tool.LayoutPrefix.Length == 0 ? root : Path.Combine(root, Program.Safe(tool.LayoutPrefix));
            void Copy(string source, string relative)
            {
                var target = Path.Combine(destination, Program.Safe(relative));
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                if (File.Exists(target))
                {
                    if (!File.ReadAllBytes(source).AsSpan().SequenceEqual(File.ReadAllBytes(target)))
                    {
                        throw new InvalidDataException("Conflicting build tool input: " + relative);
                    }
                }
                else
                {
                    File.Copy(source, target);
                }
            }
            foreach (var directory in tool.Directories)
            {
                foreach (var file in tool.Native ? ArtifactLayouts.Files(directory).Select(path => new Input(path, Path.GetRelativePath(directory, path))) : RuntimePackages.Files(directory, tool.Packages ?? []))
                {
                    Copy(file.Source, file.Path);
                }
            }

            foreach (var input in tool.Data)
            {
                Copy(input.Source, input.Path);
            }

            if (!File.Exists(Path.Combine(root, Program.Safe(tool.EntryPoint))))
            {
                throw new InvalidDataException("Missing build tool entry: " + tool.EntryPoint);
            }
        }
    }
    internal static void Validate(Session session, ProjectInstance evaluated)
    {
        var bound = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        Bind(session, bound);
        foreach (var (name, path) in bound)
        {
            if (evaluated.GetPropertyValue(name) != path)
            {
                throw new InvalidDataException("Bound tool property was overridden: " + name);
            }
        }
    }
    internal static void Bind(Session session, Dictionary<string, string> properties)
    {
        foreach (var binding in session.Request.FileBindings ?? [])
        {
            XmlConvert.VerifyNCName(binding.Property);
            if (binding.Property.StartsWith("MSBuild", StringComparison.OrdinalIgnoreCase) || binding.Property.StartsWith("Restore", StringComparison.OrdinalIgnoreCase) || binding.Property.StartsWith("_Bazel", StringComparison.OrdinalIgnoreCase) || properties.ContainsKey(binding.Property))
            {
                throw new InvalidDataException("Reserved or conflicting bound property: " + binding.Property);
            }

            var tools = session.Request.BuildTools ?? [];
            if (binding.Tool < 0 || binding.Tool >= tools.Length)
            {
                throw new InvalidDataException("Undeclared bound tool");
            }

            properties.Add(binding.Property, Path.Combine(DirectoryPath(session.Workspace, binding.Tool), Program.Safe(tools[binding.Tool].EntryPoint)));
        }
    }
}
