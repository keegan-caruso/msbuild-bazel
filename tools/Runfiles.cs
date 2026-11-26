namespace RulesMSBuild;

// The caller supplies either a runfiles tree or its declared Bazel manifest.
// Logical keys remain case-sensitive, including on Windows.
internal sealed class Runfiles
{
    private readonly string? root;
    private readonly Dictionary<string, string> entries = new(StringComparer.Ordinal);

    internal Runfiles(string rootOrManifest)
    {
        var path = Path.GetFullPath(rootOrManifest);
        if (Directory.Exists(path))
        {
            root = path;
            return;
        }
        if (!File.Exists(path))
        {
            throw new FileNotFoundException("Missing runfiles directory or manifest", path);
        }
        foreach (var line in File.ReadLines(path))
        {
            if (line.Length == 0)
            {
                throw new InvalidDataException("Empty runfiles manifest entry");
            }
            var escaped = line[0] == ' ';
            var record = escaped ? line[1..] : line;
            var separator = record.IndexOf(' ');
            var logical = separator < 0 ? record : record[..separator];
            var physical = separator < 0 ? record : record[(separator + 1)..];
            if (escaped)
            {
                logical = Decode(logical);
                physical = Decode(physical);
            }
            Safe(logical);
            if (physical.Length == 0 || physical.Contains('\0'))
            {
                throw new InvalidDataException("Empty or invalid runfiles manifest target: " + logical);
            }
            physical = Path.GetFullPath(physical);
            if (entries.TryGetValue(logical, out var previous) && !PhysicalEquals(previous, physical))
            {
                throw new InvalidDataException("Conflicting duplicate runfiles manifest entry: " + logical);
            }
            entries[logical] = physical;
        }
    }

    internal string Resolve(string logicalPath)
    {
        Safe(logicalPath);
        string? physical = root is null ? null : Path.GetFullPath(logicalPath, root);
        if (root is null && !entries.TryGetValue(logicalPath, out physical))
        {
            for (var separator = logicalPath.LastIndexOf('/'); separator >= 0; separator = logicalPath.LastIndexOf('/', separator - 1))
            {
                if (entries.TryGetValue(logicalPath[..separator], out var ancestor))
                {
                    physical = Path.GetFullPath(logicalPath[(separator + 1)..], ancestor);
                    break;
                }
            }
        }
        if (physical is null)
        {
            throw new FileNotFoundException("Missing declared runfile: " + logicalPath, physical);
        }
        return physical;
    }

    private static void Safe(string path)
    {
        if (!RelativePathComponents.IsSafeRelative(path) || path.Contains('\0'))
        {
            throw new InvalidDataException("Expected a safe logical runfiles path: " + path);
        }
    }

    private static bool PhysicalEquals(string left, string right) => string.Equals(left, right,
        OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal);

    private static string Decode(string value)
    {
        var result = new System.Text.StringBuilder();
        for (var index = 0; index < value.Length; index++)
        {
            var character = value[index];
            if (character == '\\')
            {
                if (++index == value.Length)
                {
                    throw new InvalidDataException("Incomplete runfiles manifest escape");
                }
                character = value[index] switch
                {
                    's' => ' ',
                    'n' => '\n',
                    'b' => '\\',
                    _ => throw new InvalidDataException("Unknown runfiles manifest escape"),
                };
            }
            result.Append(character);
        }
        return result.ToString();
    }
}
