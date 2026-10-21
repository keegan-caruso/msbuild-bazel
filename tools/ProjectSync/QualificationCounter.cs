using Microsoft.Build.Framework;

namespace RulesMSBuild.ProjectSync;

internal sealed class QualificationCounter : ILogger
{
    private int compilations;
    internal int Compilations => compilations;
    public LoggerVerbosity Verbosity
    {
        get; set;
    }
    public string? Parameters
    {
        get; set;
    }
    public void Initialize(IEventSource eventSource) => eventSource.TaskStarted += (_, args) =>
    {
        if (args.TaskName == "Csc")
        {
            Interlocked.Increment(ref compilations);
        }
    };
    public void Shutdown()
    {
    }
}
