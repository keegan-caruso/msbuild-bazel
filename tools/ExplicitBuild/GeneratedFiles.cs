using System.Xml;
using Microsoft.Build.Execution;

internal static class GeneratedFiles
{
    private static string PathFor(string state, string name) => Path.Combine(state, "generated", Program.Safe(name));
    internal static void Bind(Session session, Dictionary<string, string> properties)
    {
        var request = session.Request;
        foreach (var target in request.GenerateTargets ?? [])
        {
            XmlConvert.VerifyNCName(target);
        }

        foreach (var name in request.GeneratedOutputs?.Keys ?? Enumerable.Empty<string>())
        {
            Directory.CreateDirectory(Path.GetDirectoryName(PathFor(session.State, name))!);
        }

        foreach (var (property, name) in request.OutputProperties ?? [])
        {
            XmlConvert.VerifyNCName(property);
            if (property.StartsWith("MSBuild", StringComparison.OrdinalIgnoreCase) || property.StartsWith("Restore", StringComparison.OrdinalIgnoreCase) || property.StartsWith("_Bazel", StringComparison.OrdinalIgnoreCase) || properties.ContainsKey(property))
            {
                throw new InvalidDataException("Reserved or conflicting output property: " + property);
            }

            if (request.GeneratedOutputs is null || !request.GeneratedOutputs.ContainsKey(name))
            {
                throw new InvalidDataException("Undeclared generated output: " + name);
            }

            properties.Add(property, PathFor(session.State, name));
        }
    }
    internal static void Validate(Session session, ProjectInstance evaluated)
    {
        foreach (var (property, name) in session.Request.OutputProperties ?? [])
        {
            if (evaluated.GetPropertyValue(property) != PathFor(session.State, name))
            {
                throw new InvalidDataException("Bound output property was overridden: " + property);
            }
        }
    }
    internal static void Publish(Request request, string state)
    {
        foreach (var (name, destination) in request.GeneratedOutputs ?? [])
        {
            var source = PathFor(state, name);
            if (!File.Exists(source))
            {
                throw new InvalidDataException("Missing declared generated output: " + name);
            }

            for (var path = source; path != state; path = Path.GetDirectoryName(path)!)
            {
                if (File.GetAttributes(path).HasFlag(FileAttributes.ReparsePoint))
                {
                    throw new InvalidDataException("Generated output contains a link");
                }
            }

            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(destination))!);
            File.Copy(source, destination, true);
        }
    }
}
