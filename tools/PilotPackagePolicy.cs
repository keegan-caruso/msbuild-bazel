using System.Reflection;
using System.Text.Json;

internal static class PilotPackagePolicy
{
    private static readonly Dictionary<string, PilotPackagePin> Pins = Load();
    private static Dictionary<string, PilotPackagePin> Load()
    {
        using var input = Assembly.GetExecutingAssembly().GetManifestResourceStream("pilot-package-policy.json")!;
        var pins = JsonSerializer.Deserialize<Dictionary<string, PilotPackagePin>>(input, new JsonSerializerOptions { PropertyNameCaseInsensitive = true })!;
        return new Dictionary<string, PilotPackagePin>(pins, StringComparer.OrdinalIgnoreCase);
    }

    public static PilotPackagePin? Find(string identity) => Pins.GetValueOrDefault(identity);

    public static string? SelectedVersion(string packageId, string requested)
    {
        if (requested.StartsWith('[') && requested.EndsWith(']') && !requested.Contains(','))
            return requested[1..^1];
        return Pins.ContainsKey(packageId + "/" + requested) ? requested : null;
    }
}

internal sealed record PilotPackagePin(string ArchiveSha256, string RestoreContentHash, string[] AdditionalRoots, string[] AssetRoles);
