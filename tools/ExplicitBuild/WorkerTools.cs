using System.Text.Json;

// Exact startup inventory, also declared as Bazel tools. Bazel replaces a worker
// when tool contents change. Request data must never enter this inventory.
internal sealed class WorkerTools
{
    private sealed record Manifest(string[] Sdk, string[] Runner);
    private readonly HashSet<string> paths = new(StringComparer.Ordinal);
    internal int Count => paths.Count;
    internal bool Contains(string path) => paths.Contains(path);

    internal WorkerTools(string? manifestPath, string sdk)
    {
        if (manifestPath is null) return;
        Program.Safe(manifestPath);
        var manifest = JsonSerializer.Deserialize<Manifest>(File.ReadAllText(manifestPath), Program.Json)!;
        var runner = Program.Real(AppContext.BaseDirectory.TrimEnd('/'));
        void Add(string path, string expectedRoot)
        {
            Program.Safe(path);
            if (!Program.Real(path).StartsWith(expectedRoot + "/", StringComparison.Ordinal)) throw new InvalidDataException("Worker tool is outside its pinned root: " + path);
            if (!File.Exists(path)) throw new InvalidDataException("Missing worker tool: " + path);
            paths.Add(path);
        }
        foreach (var path in manifest.Sdk) Add(path, sdk);
        foreach (var path in manifest.Runner) Add(path, runner);
        paths.Add(manifestPath);
    }
}
