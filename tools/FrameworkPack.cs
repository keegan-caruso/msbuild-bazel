using System.Text.Json;

// The net8 pilot uses the SDK-requested, pinned NuGet targeting pack.
internal static class FrameworkPack
{
    public static string? Selected(JsonElement assets, string framework)
    {
        if (framework != "net8.0") return null;
        var dependencies = assets.GetProperty("project").GetProperty("frameworks").GetProperty(framework).GetProperty("downloadDependencies");
        var pack = dependencies.EnumerateArray().Single(item => item.GetProperty("name").GetString() == "Microsoft.NETCore.App.Ref");
        if (pack.GetProperty("version").GetString()?.Replace(" ", "", StringComparison.Ordinal) != "[8.0.30,8.0.30]")
            throw new InvalidDataException("unsupported-framework-pack: expected Microsoft.NETCore.App.Ref 8.0.30");
        return "Microsoft.NETCore.App.Ref/8.0.30";
    }
}
