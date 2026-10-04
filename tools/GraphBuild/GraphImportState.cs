using Microsoft.Build.Execution;

namespace RulesMSBuild.GraphBuild;

internal static class GraphImportState
{
    internal static string FingerprintValue(ProjectInstance project, IEnumerable<string> imports, string value)
    {
        // MSBuild prepends the newest project/import to this incremental input
        // list. Restore downloads change mtimes, not content. Key that prefix on
        // every validated import instead; retain authored entries and the original
        // build instance so SDK incremental decisions stay with MSBuild.
        var paths = imports.Append(project.FullPath).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
        var separator = value.IndexOf(';');
        var newest = separator < 0 ? value : value[..separator];
        if (!paths.Contains(newest, StringComparer.Ordinal))
        {
            return value;
        }
        return string.Join(';', paths) + (separator < 0 ? "" : value[separator..]);
    }
}
