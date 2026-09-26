using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Xml.Linq;

// Internal experiment, enabled only by the explicit qualification define.
// Qualify task/package/analyzer loading before expanding this bounded slice.
internal static class StableWorkerPaths
{
    internal static string ProjectKey(Request r)
    {
        Validate(r);

        // Only logical configuration belongs here. Content, dependency membership,
        // physical input/output roots and worker identity deliberately do not.
        var descriptor = JsonSerializer.Serialize(new
        {
            version = 1,
            target = r.ExperimentalWorkerProject,
            project = r.Project.Path,
            r.Assembly,
            r.Framework,
            r.Configuration,
            r.OutputMode,
            r.Executable,
            r.UseAppHost,
            r.SdkVersion,
            properties = r.Properties.OrderBy(p => p.Key, StringComparer.Ordinal).ToArray(),
            defines = r.Defines.Order(StringComparer.Ordinal).ToArray(),
            r.Nullable,
            r.LanguageVersion,
            r.AllowUnsafe
        });
        return Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(descriptor)));
    }

    private static void Validate(Request r)
    {
        if (string.IsNullOrWhiteSpace(r.ExperimentalWorkerProject) || r.Packages.Length != 0 ||
            r.BuildTools is { Length: > 0 } || r.ProjectAnalyzers is { Length: > 0 } ||
            r.LayoutBindings is { Length: > 0 } || r.FrameworkInputs is not null ||
            r.ProjectOutputs is { Length: > 0 } || r.TargetInputs is { Length: > 0 } ||
            r.RestoreInput is not null || r.RestoreOnly ||
            r.GeneratedDirectories is { Count: > 0 } || r.GenerateTargets is { Length: > 0 })
        {
            throw new InvalidDataException("Stable-path prototype supports SDK-only projects without package/tool/prepared inputs");
        }

        foreach (var input in r.Imports.Concat(r.AdapterImports ?? []).Prepend(r.Project))
        {
            var xml = XDocument.Load(input.Source);
            if (xml.Descendants().Any(e => e.Name.LocalName is "UsingTask" or "Sdk" || e.Name.LocalName == "Import" && e.Attribute("Sdk") is not null) ||
                input == r.Project && xml.Root?.Attribute("Sdk")?.Value != "Microsoft.NET.Sdk")
            {
                throw new InvalidDataException("Stable-path prototype does not support custom SDKs or task registrations");
            }
        }
    }

    internal static Dictionary<string, string> StageReferences(Request r, string workspace, string root, Dictionary<string, string> digests)
    {
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var reference in r.References)
        {
            if (!digests.TryGetValue(reference, out var digest))
            {
                throw new InvalidDataException("Undeclared stable-path reference: " + reference);
            }

            var file = Path.GetFileName(reference);
            var path = Path.Combine(root, digest, file);
            Program.Copy(reference, path);
            var staged = Path.Combine(workspace, ".references", file);
            if (result.TryGetValue(staged, out var existing) && existing != path)
            {
                throw new InvalidDataException("Conflicting stable-path reference: " + file);
            }

            result[staged] = path;
        }
        return result;
    }
}
