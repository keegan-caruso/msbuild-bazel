using System.Text.Json;

internal sealed record LayoutRequest(string Output);
internal sealed record LayoutEntry(string Source, string Path, bool Directory = false);
internal sealed record RuntimeHost(string Directory, string EntryPoint, string LaunchMode = "dotnet", string RuntimeIdentifier = "", string Version = "", Dictionary<string, string>? Environment = null);

internal static class ArtifactLayouts
{
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
}
