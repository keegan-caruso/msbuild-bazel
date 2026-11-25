using Microsoft.Build.Framework;

namespace RulesMSBuild.GraphBuild;

// Graph evaluation happens before BuildManager starts. Events here count fresh
// evaluations performed by build nodes after receiving the evaluated instances.
internal sealed class BuildEvaluationCounter : ILogger
{
    private long evaluations;
    private long compilerTasks;
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, int> compilerProjects = new(StringComparer.Ordinal);
    internal IReadOnlyDictionary<string, int> CompilerProjects => compilerProjects;
    internal long CompilerTasks => Interlocked.Read(ref compilerTasks);
    internal long Evaluations => Interlocked.Read(ref evaluations);
    public LoggerVerbosity Verbosity { get; set; } = LoggerVerbosity.Diagnostic;
    public string? Parameters
    {
        get; set;
    }

    public void Initialize(IEventSource source)
    {
        source.TaskStarted += (_, args) =>
        {
            if (args.TaskName is "Csc" or "Vbc" or "Fsc")
            {
                Interlocked.Increment(ref compilerTasks);
                compilerProjects.AddOrUpdate(args.ProjectFile ?? "", 1, (_, count) => count + 1);
            }
        };
        source.StatusEventRaised += (_, args) =>
        {
            if (args is ProjectEvaluationStartedEventArgs)
            {
                Interlocked.Increment(ref evaluations);
            }
        };
    }

    public void Shutdown()
    {
    }
}
