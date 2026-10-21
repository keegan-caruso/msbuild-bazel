using System.Text.Json;
using RulesMSBuild.ProjectCache;

namespace RulesMSBuild.ProjectSync;

// Private writable copies must not share inodes with declared inputs or the CAS.
// CoW clones preserve that boundary; unsupported filesystems use ordinary copies.
internal static class SyncFiles
{
    private static readonly FileMaterializer Materializer = new(true, Environment.GetEnvironmentVariable("RULES_MSBUILD_SYNC_PROFILE") == "1");

    internal static void Copy(string source, string destination, bool overwrite = false, string? expectedDigest = null)
    {
        if (!overwrite && Path.Exists(destination))
        {
            throw new IOException("Sync copy destination already exists: " + destination);
        }
        Materializer.Copy(source, destination, expectedDigest);
    }

    internal static void Report()
    {
        if (Materializer.Report is { } report)
        {
            Console.Error.WriteLine("PROJECT_SYNC_FILES " + JsonSerializer.Serialize(report));
        }
    }
}
