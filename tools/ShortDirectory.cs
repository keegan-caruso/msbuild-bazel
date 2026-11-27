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
                link = alias;
                try
                {
                    Directory.CreateSymbolicLink(link, Path);
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
