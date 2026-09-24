using System.Text.Json;
using System.Xml;
using Microsoft.Build.Execution;

internal sealed record LayoutRequest(string Output);
internal sealed record LayoutEntry(string Source, string Path, bool Directory = false);
internal sealed record LayoutBinding(string Directory, string Property);
internal sealed record RuntimeHost(string Directory, string EntryPoint);

internal static class ArtifactLayouts
{
    // Layouts are immutable action outputs. Refuse links, including directory
    // links, so declared trees cannot acquire undeclared external contents.
    internal static IEnumerable<string> Files(string root)
    {
        foreach (var path in Directory.EnumerateFileSystemEntries(root))
        {
            var attributes = File.GetAttributes(path);
            if (attributes.HasFlag(FileAttributes.ReparsePoint))
            {
                throw new InvalidDataException("Artifact layout contains a link: " + path);
            }

            if (attributes.HasFlag(FileAttributes.Directory))
            {
                foreach (var child in Files(path))
                {
                    yield return child;
                }
            }
            else
            {
                yield return path;
            }
        }
    }
    private static void CopyTree(string source, string destination)
    {
        Directory.CreateDirectory(destination);
        foreach (var file in Files(source))
        {
            Program.Copy(file, Path.Combine(destination, Program.Safe(Path.GetRelativePath(source, file))));
        }
    }
    internal static void Compose(LayoutRequest request, string manifest)
    {
        Directory.CreateDirectory(request.Output);
        foreach (var line in File.ReadLines(manifest))
        {
            var input = JsonSerializer.Deserialize<LayoutEntry>(line, Program.Json)!;
            var destination = input.Directory && input.Path == "." ? request.Output : Path.Combine(request.Output, Program.Safe(input.Path));
            if (input.Directory)
            {
                Directory.CreateDirectory(destination);
            }
            else
            {
                // The manifest lists individual Bazel inputs. Sandbox symlinks
                // are valid here; never recursively discover files through them.
                Program.Copy(input.Source, destination);
            }
        }
    }
    internal static void Stage(Request request, string workspace)
    {
        var bindings = request.LayoutBindings ?? [];
        for (var i = 0; i < bindings.Length; i++)
        {
            CopyTree(bindings[i].Directory, Path.Combine(workspace, ".layouts", i.ToString(System.Globalization.CultureInfo.InvariantCulture)));
        }

        if (request.FrameworkInputs is not null)
        {
            var directory = Path.Combine(workspace, ".framework");
            Directory.CreateDirectory(directory);
            foreach (var file in request.FrameworkInputs)
            {
                Program.Copy(file, Path.Combine(directory, Path.GetFileName(file)));
            }
        }
    }
    internal static void Bind(Session session, Dictionary<string, string> properties)
    {
        var bindings = session.Request.LayoutBindings ?? [];
        for (var i = 0; i < bindings.Length; i++)
        {
            var name = bindings[i].Property;
            XmlConvert.VerifyNCName(name);
            if (name.StartsWith("MSBuild", StringComparison.OrdinalIgnoreCase) || name.StartsWith("Restore", StringComparison.OrdinalIgnoreCase) || name.StartsWith("_Bazel", StringComparison.OrdinalIgnoreCase) || properties.ContainsKey(name))
            {
                throw new InvalidDataException("Reserved or conflicting layout property: " + name);
            }

            properties.Add(name, Path.Combine(session.Workspace, ".layouts", i.ToString(System.Globalization.CultureInfo.InvariantCulture)) + "/");
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
                throw new InvalidDataException("Bound layout property was overridden: " + name);
            }
        }

        if (session.Request.FrameworkInputs is not null && evaluated.GetItems("FrameworkReference").Count != 0)
        {
            throw new InvalidDataException("Explicit reference_pack cannot use implicit or named FrameworkReference packs");
        }
    }
}
