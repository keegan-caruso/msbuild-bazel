using System.Reflection;
using System.Text.Json.Nodes;
using ActionRunner;

// SDK asset-query and copy targets reference these intermediate manifests.
// Store portable paths in bundles and expand them only in the private build tree.
internal static class StaticWebAssets
{
    internal static bool Intermediate(string project, string framework, string path)
    {
        var folder = Path.Combine(Path.GetDirectoryName(project)!, "obj/Release", framework);
        return new[] { "staticwebassets.build.json", "staticwebassets.build.endpoints.json", "staticwebassets.development.json" }
            .Any(name => path == Path.Combine(folder, name));
    }
    private static bool Manifest(string path) => Path.GetFileName(path) is "staticwebassets.build.json" or "staticwebassets.build.endpoints.json" or "staticwebassets.development.json" ||
        path.EndsWith(".staticwebassets.runtime.json", StringComparison.Ordinal) || path.EndsWith(".staticwebassets.endpoints.json", StringComparison.Ordinal);
    private static readonly Lazy<Type> ManifestType = new(() => Assembly.LoadFrom(Path.Combine(Path.GetDirectoryName(Environment.ProcessPath!)!, "sdk/10.0.400/Sdks/Microsoft.NET.Sdk.StaticWebAssets/tasks/net10.0/Microsoft.NET.Sdk.StaticWebAssets.Tasks.dll"))
        .GetType("Microsoft.AspNetCore.StaticWebAssets.Tasks.StaticWebAssetsManifest", throwOnError: true)!);
    private static string Hash(string text)
    {
        var type = ManifestType.Value;
        var value = type.GetMethod("FromJsonString", BindingFlags.Public | BindingFlags.Static)!.Invoke(null, [text]);
        return (string)type.GetMethod("ComputeManifestHash", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(value, null)!;
    }
    private static string Rebase(string text, string before, string after)
    {
        var original = JsonNode.Parse(text)!;
        if (original["Hash"] is not null && original["Hash"]!.GetValue<string>() != Hash(text)) throw new InvalidDataException("Static web assets manifest hash differs from SDK contents");
        var rebased = text.Replace(before, after, StringComparison.Ordinal);
        if (original["Hash"] is null) return rebased;
        var document = JsonNode.Parse(rebased)!;
        document["Hash"] = Hash(rebased);
        return document.ToJsonString();
    }
    internal static void Capture(string source, string destination, string workspace)
    {
        Files.Copy(source, destination);
        if (Manifest(source)) File.WriteAllText(destination, Rebase(File.ReadAllText(source), workspace, "/_/workspace"));
    }
    internal static void Restore(string source, string destination, string workspace)
    {
        Files.Copy(source, destination);
        if (Manifest(source)) File.WriteAllText(destination, Rebase(File.ReadAllText(source), "/_/workspace", workspace));
    }
}
