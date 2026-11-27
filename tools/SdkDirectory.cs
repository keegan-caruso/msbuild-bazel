namespace RulesMSBuild;

// MSBuild's Windows Exists condition uses a Win32 path check even when managed
// reads support the longer physical paths used by Bazel's repository cache.
// Keep SDK evaluation under a short, owned directory link without copying it.
internal sealed class SdkDirectory : IDisposable
{
    private readonly string? temporary;
    private readonly string? link;

    internal string Path
    {
        get;
    }

    internal SdkDirectory(string directory)
    {
        var selected = System.IO.Path.GetFullPath(directory);
        if (!File.Exists(System.IO.Path.Combine(selected, "MSBuild.dll")))
        {
            throw new ArgumentException("sdk-directory must contain MSBuild.dll");
        }
        var root = System.IO.Path.GetDirectoryName(System.IO.Path.GetDirectoryName(selected))!;
        if (!OperatingSystem.IsWindows())
        {
            Path = selected;
            return;
        }
        var candidate = Directory.CreateTempSubdirectory("msbuild-sdk-").FullName;
        var alias = System.IO.Path.Combine(candidate, "sdk");
        if (root.Length <= alias.Length)
        {
            // Preserve already-short declared roots, including an AppContainer's
            // private drive. Never expand them into inaccessible host paths.
            Directory.Delete(candidate);
            Path = selected;
            return;
        }
        temporary = candidate;
        link = alias;
        try
        {
            Directory.CreateSymbolicLink(link, root);
            Path = System.IO.Path.Combine(link, System.IO.Path.GetRelativePath(root, selected));
        }
        catch
        {
            Dispose();
            throw;
        }
    }

    public void Dispose()
    {
        if (link is not null && new DirectoryInfo(link).LinkTarget is not null)
        {
            // Never recursively delete through the declared SDK link.
            Directory.Delete(link);
        }
        if (temporary is not null)
        {
            Directory.Delete(temporary);
        }
    }
}
