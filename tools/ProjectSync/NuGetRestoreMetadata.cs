using System.Text.Json;

namespace RulesMSBuild.ProjectSync;

// One snapshot per capture point, shared by lock and configuration validation.
// Extract owned values before disposing the document; no assets DOM is retained.
internal sealed record NuGetRestoreMetadata(string ProjectPath, string[] ConfigFilePaths)
{
    internal static NuGetRestoreMetadata[] Read(string workspace) =>
        Directory.GetFiles(workspace, "project.assets.json", SearchOption.AllDirectories).Select(assets =>
        {
            using var stream = File.OpenRead(assets);
            using var document = JsonDocument.Parse(stream);
            var restore = document.RootElement.GetProperty("project").GetProperty("restore");
            return new NuGetRestoreMetadata(restore.GetProperty("projectPath").GetString()!,
                restore.GetProperty("configFilePaths").EnumerateArray().Select(item => item.GetString()!).ToArray());
        }).ToArray();
}
