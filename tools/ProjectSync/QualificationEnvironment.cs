using System.Security.Cryptography;
using System.Text;
using RulesMSBuild.ProjectCache;

namespace RulesMSBuild.ProjectSync;

// SDK/system mounts are read-only for the whole qualification invocation.
// Share their byte identity between Restore and compiler qualification keys.
internal sealed record QualificationEnvironment(string Identity)
{
    internal static QualificationEnvironment Create(string sdk)
    {
        using var profile = SyncProfile.Measure("qualification-environment");
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        Add("qualification-environment-v1");
        Add(System.Runtime.InteropServices.RuntimeInformation.RuntimeIdentifier);
        Add(Math.Clamp(Environment.ProcessorCount, 1, 4).ToString(System.Globalization.CultureInfo.InvariantCulture));
        Add(SnapshotPayloads.Digest(typeof(QualificationEnvironment).Assembly.Location));
        foreach (var path in new[] { "/etc/os-release", "/usr/bin/bwrap", "/bin/sh" })
        {
            Add(path);
            File(path);
        }
        foreach (var path in Directory.EnumerateFiles(sdk, "*", SearchOption.AllDirectories).Order(StringComparer.Ordinal))
        {
            Add(Path.GetRelativePath(sdk, path));
            File(path);
        }
        return new(Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant());

        void File(string path)
        {
            Add(SnapshotPayloads.Digest(path));
            Add((OperatingSystem.IsWindows() ? 0 : (int)System.IO.File.GetUnixFileMode(path) & 511).ToString(System.Globalization.CultureInfo.InvariantCulture));
        }
        void Add(string value)
        {
            var bytes = Encoding.UTF8.GetBytes(value);
            hash.AppendData(BitConverter.GetBytes(bytes.Length));
            hash.AppendData(bytes);
        }
    }
}
