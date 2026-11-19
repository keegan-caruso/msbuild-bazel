namespace RulesMSBuild;

// Logical paths use '/' on every host. Filesystem containment, symlink checks
// and caller-specific character restrictions remain the caller's responsibility.
internal static class RelativePathComponents
{
    internal static bool IsSafeRelative(string path)
    {
        if (Path.IsPathRooted(path) || path.Contains('\\'))
        {
            return false;
        }
        var value = path.AsSpan();
        foreach (var range in value.Split('/'))
        {
            var component = value[range];
            if (component.IsEmpty || component.SequenceEqual(".") || component.SequenceEqual(".."))
            {
                return false;
            }
        }
        return true;
    }
}
