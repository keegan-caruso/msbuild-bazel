namespace RulesMSBuild.ProjectSync;

// Resolve afresh at every verification boundary so a Build cannot introduce
// a leaf or ancestor link after an earlier check.
internal static class QualificationPaths
{
    internal static string Resolve(string root, string path, string message)
    {
        var target = Path.Combine(root, WorkspaceView.Safe(path));
        for (var current = target; current.Length >= root.Length; current = Path.GetDirectoryName(current)!)
        {
            if (new FileInfo(current).LinkTarget is not null)
            {
                throw new InvalidDataException(message + current);
            }
            if (current == root)
            {
                break;
            }
        }
        return target;
    }
}
