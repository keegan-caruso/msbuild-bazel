using System.Collections.Concurrent;
using Microsoft.Build.Framework;

namespace RulesMSBuild.GraphBuild;

// Evaluation-only diagnostics. MSBuild operation sums overlap parallel projects
// and parent passes; exclusive file totals do not include unlocated operations.
internal sealed class GraphEvaluationProfile(ContractFiles files) : ILogger
{
    private readonly ConcurrentDictionary<string, double> exclusiveFiles = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, byte> imports = new(StringComparer.Ordinal);
    private long configuredProjects;
    private long importRecords;
    private long profiledProjects;
    public LoggerVerbosity Verbosity { get; set; } = LoggerVerbosity.Minimal;
    public string? Parameters
    {
        get; set;
    }
    internal object Report => new
    {
        configuredProjects,
        profiledProjects,
        importRecords,
        distinctImports = imports.Count,
        exclusiveFiles = exclusiveFiles.OrderByDescending(pair => pair.Value).ThenBy(pair => pair.Key, StringComparer.Ordinal)
            .Take(20).ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal)
    };

    internal void Project(string[] paths)
    {
        Interlocked.Increment(ref configuredProjects);
        Interlocked.Add(ref importRecords, paths.Length);
        foreach (var path in paths)
        {
            imports.TryAdd(files.Normalize(path), 0);
        }
    }

    public void Initialize(IEventSource source) => source.StatusEventRaised += Finished;
    public void Shutdown()
    {
    }

    private void Finished(object sender, BuildStatusEventArgs args)
    {
        if (args is not ProjectEvaluationFinishedEventArgs { ProfilerResult: { } profile })
        {
            return;
        }
        Interlocked.Increment(ref profiledProjects);
        foreach (var (location, timing) in profile.ProfiledLocations)
        {
            if (location.IsEvaluationPass)
            {
                GraphProfile.Record("msbuildEvaluation/" + location.EvaluationPass, timing.InclusiveTime, 1);
            }
            else if (!string.IsNullOrEmpty(location.File))
            {
                exclusiveFiles.AddOrUpdate(files.Normalize(location.File), timing.ExclusiveTime.TotalSeconds,
                    (_, seconds) => seconds + timing.ExclusiveTime.TotalSeconds);
            }
        }
    }
}
