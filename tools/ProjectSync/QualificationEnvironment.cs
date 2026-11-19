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
            Add(SnapshotPayloads.Digest(path));
            Add(Mode(path));
        }
        AddSdk(sdk, Add);
        return new(Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant());

        void Add(string value)
        {
            var bytes = Encoding.UTF8.GetBytes(value);
            hash.AppendData(BitConverter.GetBytes(bytes.Length));
            hash.AppendData(bytes);
        }
    }

    private static void AddSdk(string sdk, Action<string> add)
    {
        var sdkRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(sdk)) + Path.DirectorySeparatorChar;
        var digests = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var path in Directory.EnumerateFiles(sdk, "*", SearchOption.AllDirectories).Order(StringComparer.Ordinal))
        {
            add(Path.GetRelativePath(sdk, path));
            // Only reuse resolved file targets inside this immutable SDK. A
            // directory alias or hard link may miss reuse without changing identity.
            var physical = File.ResolveLinkTarget(path, true)?.FullName ?? Path.GetFullPath(path);
            var reusable = physical.StartsWith(sdkRoot, StringComparison.Ordinal);
            if (!reusable || !digests.TryGetValue(physical, out var digest))
            {
                digest = SnapshotPayloads.Digest(path);
                if (reusable)
                {
                    digests[physical] = digest;
                }
            }
            add(digest);
            add(Mode(path));
        }
    }

    private static string Mode(string path) => (OperatingSystem.IsWindows() ? 0 : (int)File.GetUnixFileMode(path) & 511)
        .ToString(System.Globalization.CultureInfo.InvariantCulture);
}
