using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace RulesMSBuild.ProjectCache;

// An observation belongs to one verification boundary. Do not retain it across
// a Build: unchanged timestamps do not prove unchanged input contents.
internal sealed record FileObservation(string ContentDigest, int Mode)
{
    internal static FileObservation Read(string path)
    {
        using var stream = File.OpenRead(path);
        return new(Convert.ToHexString(SHA256.HashData(stream)),
            OperatingSystem.IsWindows() ? 0 : (int)File.GetUnixFileMode(path));
    }

    internal string QualificationDigest => ContentDigest.ToLowerInvariant() + ":" + (Mode & 511).ToString(CultureInfo.InvariantCulture);
    internal string SeedDigest => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(
        ContentDigest + ":" + Mode.ToString(CultureInfo.InvariantCulture))));
}
