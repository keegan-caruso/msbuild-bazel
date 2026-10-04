using Microsoft.Build.Framework;

namespace RulesMSBuild.GraphBuild;

// Graph evaluation happens before BuildManager starts. Events here count fresh
// evaluations performed by build nodes after receiving the evaluated instances.
internal sealed class BuildEvaluationCounter : ILogger
{
    private long evaluations;
    internal long Evaluations => Interlocked.Read(ref evaluations);
    public LoggerVerbosity Verbosity { get; set; } = LoggerVerbosity.Diagnostic;
    public string? Parameters
    {
        get; set;
    }

    public void Initialize(IEventSource source) => source.StatusEventRaised += (_, args) =>
    {
        if (args is ProjectEvaluationStartedEventArgs)
        {
            Interlocked.Increment(ref evaluations);
        }
    };

    public void Shutdown()
    {
    }
}
