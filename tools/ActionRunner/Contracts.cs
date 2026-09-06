using System.Text.Json;

namespace ActionRunner;

internal sealed record InputFile(string Source, string Destination);

internal sealed record ActionRequest(
    string Project, InputFile[] Sources, string[] Restore, InputFile[] Packages,
    string? PackageManifest, string Plugin, string Output, string Diagnostics,
    string? Dependency, string UndeclaredProbe, string? NativeManifest, InputFile[] NativeFiles);

internal sealed record Artifact(string Path, long Size, string Sha256);
internal sealed record PackageFile(string Path, long Size, string Sha256);
internal sealed record Package(string Id, string Version, string Path, PackageFile[] Files);
internal sealed record PackageManifest(int SchemaVersion, Package[] Packages);
internal sealed record NativeManifest(int SchemaVersion, string[] Files);

internal static class JsonFiles
{
    private static readonly JsonSerializerOptions RequestOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
    };
    internal static readonly JsonSerializerOptions OutputOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true
    };

    public static ActionRequest ReadRequest(string path) =>
        JsonSerializer.Deserialize<ActionRequest>(File.ReadAllText(path), RequestOptions)
        ?? throw new InvalidDataException("empty action request");

    public static T Read<T>(string path) =>
        JsonSerializer.Deserialize<T>(File.ReadAllText(path), OutputOptions)
        ?? throw new InvalidDataException("empty JSON: " + path);

    public static void Write<T>(string path, T value) =>
        File.WriteAllText(path, JsonSerializer.Serialize(value, OutputOptions) + "\n");
}
