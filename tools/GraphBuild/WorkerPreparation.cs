using System.Text.Json;

namespace RulesMSBuild.GraphBuild;

// The broker owns these materialized artifacts. Children only see read-only
// mounts; every request still validates payload bytes in PreparedRestore.Apply.
internal static class WorkerPreparation
{
    internal static string Materialize(string artifact, string cache, string? inputIdentity = null)
    {
        var manifestPath = Path.Combine(artifact, "prepared", "manifest.json");
        var file = new FileInfo(manifestPath);
        var source = Path.GetDirectoryName(file.ResolveLinkTarget(returnFinalTarget: true)?.FullName ?? file.FullName)!;
        var bytes = File.ReadAllBytes(Path.Combine(source, "manifest.json"));
        var digest = Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(bytes));
        var destination = Path.Combine(cache, ContractFiles.Hash([digest, inputIdentity ?? Guid.NewGuid().ToString("N")]));
        if (Directory.Exists(destination))
        {
            return destination;
        }
        var manifest = JsonSerializer.Deserialize<RestoreManifest>(bytes) ?? throw new InvalidDataException("Missing preparation manifest");
        if (manifest.Version != 1)
        {
            throw new InvalidDataException("Unsupported preparation manifest");
        }
        var inputs = new ContractFiles(source, source).ResolveInputs(manifest.Files.Keys);
        var staging = destination + ".pending-" + Guid.NewGuid().ToString("N");
        try
        {
            var root = Path.Combine(staging, "prepared");
            Directory.CreateDirectory(Path.Combine(root, ".nuget"));
            foreach (var (relative, record) in manifest.Files)
            {
                if ((record.Mode & ~0xFFF) != 0)
                {
                    throw new InvalidDataException("Invalid prepared file mode: " + relative);
                }
                var target = Path.Combine(root, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                File.Copy(inputs[relative], target);
                // Copy only: PreparedRestore.Apply verifies all bytes before any
                // workspace writes or MSBuild evaluation. This private copy is
                // mounted read-only in that child, including on cache reuse.
                if (!OperatingSystem.IsWindows())
                {
                    File.SetUnixFileMode(target, (UnixFileMode)record.Mode);
                }
            }
            File.WriteAllBytes(Path.Combine(root, "manifest.json"), bytes);
            Directory.Move(staging, destination);
            return destination;
        }
        finally
        {
            if (Directory.Exists(staging))
            {
                Directory.Delete(staging, recursive: true);
            }
        }
    }
}
