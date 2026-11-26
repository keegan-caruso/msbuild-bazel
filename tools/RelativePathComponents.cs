namespace RulesMSBuild;

// Logical paths use '/' on every host. Windows additionally aliases device
// names, alternate streams and trailing dots/spaces; reject those before IO.
// Filesystem containment and reparse-point checks remain the caller's job.
internal static class RelativePathComponents
{
    // Contract keys are logical paths; native full paths are used for filesystem IO.
    internal static string LogicalRelative(string root, string path)
    {
        var relative = Path.GetRelativePath(root, path);
        return OperatingSystem.IsWindows() ? relative.Replace('\\', '/') : relative;
    }

    internal static bool IsSafeRelative(string path) => IsSafeRelative(path, OperatingSystem.IsWindows());

    internal static bool IsSafeRelative(string path, bool windows)
    {
        if (Path.IsPathRooted(path) || path.Contains('\\'))
        {
            return false;
        }
        var value = path.AsSpan();
        foreach (var range in value.Split('/'))
        {
            var component = value[range];
            if (component.IsEmpty || component.SequenceEqual(".") || component.SequenceEqual("..") ||
                windows && !IsWindowsComponent(component))
            {
                return false;
            }
        }
        return true;
    }

    private static bool IsWindowsComponent(ReadOnlySpan<char> component)
    {
        if (component[^1] is '.' or ' ' || component.IndexOfAny("<>:\"|?*") >= 0)
        {
            return false;
        }
        foreach (var character in component)
        {
            if (character < ' ')
            {
                return false;
            }
        }
        var dot = component.IndexOf('.');
        var name = (dot < 0 ? component : component[..dot]).TrimEnd(' ');
        if (name.Equals("CON", StringComparison.OrdinalIgnoreCase) || name.Equals("PRN", StringComparison.OrdinalIgnoreCase) ||
            name.Equals("AUX", StringComparison.OrdinalIgnoreCase) || name.Equals("NUL", StringComparison.OrdinalIgnoreCase) ||
            name.Equals("CONIN$", StringComparison.OrdinalIgnoreCase) || name.Equals("CONOUT$", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }
        return name.Length != 4 ||
            !(name[..3].Equals("COM", StringComparison.OrdinalIgnoreCase) || name[..3].Equals("LPT", StringComparison.OrdinalIgnoreCase)) ||
            name[3] is not (>= '1' and <= '9' or '\u00b9' or '\u00b2' or '\u00b3');
    }
}
