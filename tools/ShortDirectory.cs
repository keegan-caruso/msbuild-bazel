using System.Security.Cryptography;
using System.Text;

namespace RulesMSBuild;

// Win32 checks in MSBuild tasks can reject long paths that managed IO accepts.
// Keep an owned, shorter view without copying files or changing their identity.
internal sealed class ShortDirectory : IDisposable
{
    private readonly string? temporary;
    private readonly string? link;
    private readonly string? previousDirectory;

    internal string Path
    {
        get;
    }

    internal ShortDirectory(string directory, bool workingDirectory = false)
    {
        Path = System.IO.Path.GetFullPath(directory);
        if (OperatingSystem.IsWindows())
        {
            var candidate = Directory.CreateTempSubdirectory("msbuild-view-").FullName;
            var alias = System.IO.Path.Combine(candidate, "root");
            if (Path.Length <= alias.Length)
            {
                Directory.Delete(candidate);
            }
            else
            {
                temporary = candidate;
                try
                {
                    var physical = PhysicalPath(Path);
                    // 128 bits keep the direct leaf at least as short as the
                    // legacy view. Only the atomic creator owns its lifetime.
                    var digest = SHA256.HashData(Encoding.UTF8.GetBytes(physical));
                    var name = "msb-" + Convert.ToBase64String(digest, 0, 16).TrimEnd('=').Replace('+', '-').Replace('/', '_');
                    var stable = System.IO.Path.Combine(System.IO.Path.GetDirectoryName(candidate)!, name);
                    if (stable.Length <= alias.Length)
                    {
                        try
                        {
                            Directory.CreateSymbolicLink(stable, physical);
                            link = stable;
                        }
                        catch (IOException error) when ((error.HResult & 0xffff) is 80 or 183)
                        {
                            // An occupied leaf belongs to another invocation or
                            // stale state. Never adopt, replace or remove it.
                        }
                    }
                    if (link is null)
                    {
                        Directory.CreateSymbolicLink(alias, physical);
                        link = alias;
                    }
                    else
                    {
                        Directory.Delete(candidate);
                        temporary = null;
                    }
                    Path = link;
                }
                catch
                {
                    Dispose();
                    throw;
                }
            }
        }
        if (workingDirectory)
        {
            previousDirectory = Directory.GetCurrentDirectory();
            try
            {
                Directory.SetCurrentDirectory(Path);
            }
            catch
            {
                Dispose();
                throw;
            }
        }
    }

    internal static string PhysicalPath(string path) => PhysicalPath(path, 0);

    private static string PhysicalPath(string path, int depth)
    {
        if (depth > 64)
        {
            throw new IOException("Too many symbolic links while resolving: " + path);
        }
        var full = System.IO.Path.GetFullPath(path);
        var current = System.IO.Path.GetPathRoot(full)!;
        foreach (var part in full[current.Length..].Split(System.IO.Path.DirectorySeparatorChar, StringSplitOptions.RemoveEmptyEntries))
        {
            current = System.IO.Path.Combine(current, part);
            var info = new FileInfo(current);
            if (info.LinkTarget is not null)
            {
                // A link target can itself contain links in ancestor components.
                // Resolve that complete path before continuing with the suffix.
                current = PhysicalPath(info.ResolveLinkTarget(false)!.FullName, depth + 1);
            }
        }
        return current;
    }

    public void Dispose()
    {
        if (previousDirectory is not null)
        {
            Directory.SetCurrentDirectory(previousDirectory);
        }
        if (link is not null && new DirectoryInfo(link).LinkTarget is not null)
        {
            Directory.Delete(link);
        }
        if (temporary is not null)
        {
            Directory.Delete(temporary);
        }
    }
}
