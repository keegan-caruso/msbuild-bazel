global using File = GraphExportFile;

using System.Text;
using System.Text.Json.Nodes;

internal static class GraphExportFile
{
    public static bool Exists(string? path) => System.IO.File.Exists(path);

    public static Task<string> ReadAllTextAsync(string path) =>
        System.IO.File.ReadAllTextAsync(path);

    public static Task WriteAllTextAsync(string path, string contents, Encoding encoding) =>
        System.IO.File.WriteAllTextAsync(path, contents, encoding);

    public static void Move(string sourceFileName, string destFileName) =>
        System.IO.File.Move(sourceFileName, destFileName);

    public static Stream OpenRead(string path) =>
        System.IO.File.OpenRead(path);

    public static string ReadAllText(string path)
    {
        var text = System.IO.File.ReadAllText(path);
        if (!string.Equals(Path.GetFileName(path), "project.nuget.cache", StringComparison.OrdinalIgnoreCase))
            return text;

        var json = JsonNode.Parse(text)?.AsObject();
        if (json is null)
            return text;

        // NuGet computes dgSpecHash from the restore graph, including absolute
        // project identity. The exporter separately hashes the normalized dgspec
        // and assets inputs, so carrying this derived checkout-specific digest
        // would make equivalent restored workspaces spuriously different.
        if (json.ContainsKey("dgSpecHash"))
            json["dgSpecHash"] = "$NORMALIZED";

        return json.ToJsonString();
    }
}
