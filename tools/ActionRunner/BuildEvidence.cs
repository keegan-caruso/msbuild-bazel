using System.Text.RegularExpressions;

namespace ActionRunner;

internal sealed partial record BuildEvidence(string[] CompiledProjects, string[] ReplayHits, string[] PackageTargets)
{
    public static BuildEvidence Parse(string log) => new(
        Capture(CompileMarker(), log), Capture(ReplayMarker(), log), Capture(PackageMarker(), log));

    private static string[] Capture(Regex pattern, string log) => pattern.Matches(log)
        .Select(match => match.Groups[1].Value.Trim()).ToArray();

    public void Verify(ProjectKind project)
    {
        if (!CompiledProjects.SequenceEqual([project.ToString()]))
            throw new InvalidOperationException("unexpected project compilation: " + string.Join(", ", CompiledProjects));
        if (project == ProjectKind.App && !ReplayHits.SequenceEqual([nameof(ProjectKind.Shared)]))
            throw new InvalidOperationException("App did not replay Shared");
    }

    [GeneratedRegex(@"RULES_MSBUILD_COMPILE:([^\r\n]+)", RegexOptions.CultureInvariant)]
    private static partial Regex CompileMarker();

    [GeneratedRegex(@"RULES_MSBUILD_REPLAY_HIT:([^\r\n]*)", RegexOptions.CultureInvariant)]
    private static partial Regex ReplayMarker();

    [GeneratedRegex(@"RULES_MSBUILD_PACKAGE_TARGET:(\w+)", RegexOptions.CultureInvariant)]
    private static partial Regex PackageMarker();
}
