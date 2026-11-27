namespace RulesMSBuild;

internal sealed class SdkDirectory : IDisposable
{
    private readonly ShortDirectory view;

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
        view = new ShortDirectory(root);
        Path = System.IO.Path.Combine(view.Path, System.IO.Path.GetRelativePath(root, selected));
    }

    public void Dispose() => view.Dispose();
}
