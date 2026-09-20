using System.Diagnostics;
using System.Text.Json;
using Microsoft.Build.Framework;

// Opt-in diagnostics. Target/task totals are inclusive and must not be added
// to phase wall time (MSBuild tasks may invoke nested targets).
internal sealed class CompileProfile : ILogger
{
    private sealed record Sample(double WallSeconds, double CpuSeconds);
    private sealed class Aggregate { public int Count { get; set; } public double Seconds { get; set; } }
    private readonly Dictionary<string, Sample> phases = new(StringComparer.Ordinal);
    private readonly Dictionary<string, Aggregate> targets = new(StringComparer.Ordinal);
    private readonly Dictionary<string, Aggregate> tasks = new(StringComparer.Ordinal);
    private readonly Dictionary<string, DateTime> starts = new(StringComparer.Ordinal);
    private readonly object gate = new();
    private readonly Stopwatch clock = Stopwatch.StartNew();
    private TimeSpan cpu = Process.GetCurrentProcess().TotalProcessorTime;
    private double last;
    private static int sequence;
    private readonly int requestNumber = Interlocked.Increment(ref sequence);
    public LoggerVerbosity Verbosity { get; set; } = LoggerVerbosity.Normal;
    public string? Parameters { get; set; }
    internal void Mark(string name)
    {
        var now = clock.Elapsed.TotalSeconds; var processor = Process.GetCurrentProcess().TotalProcessorTime;
        phases.Add(name, new(now - last, (processor - cpu).TotalSeconds)); last = now; cpu = processor;
    }
    private static string Key(string kind, BuildEventContext? c) => $"{kind}:{c?.SubmissionId}:{c?.NodeId}:{c?.ProjectContextId}:{c?.TargetId}:{c?.TaskId}";
    private void Start(string key, DateTime time) { lock (gate) starts[key] = time; }
    private void Stop(string key, string name, DateTime time, Dictionary<string, Aggregate> totals)
    {
        lock (gate)
        {
            if (!starts.Remove(key, out var start)) return;
            if (!totals.TryGetValue(name, out var total)) totals.Add(name, total = new());
            total.Count++; total.Seconds += (time - start).TotalSeconds;
        }
    }
    public void Initialize(IEventSource source)
    {
        source.TargetStarted += (_, e) => Start(Key("target", e.BuildEventContext), e.Timestamp);
        source.TargetFinished += (_, e) => Stop(Key("target", e.BuildEventContext), e.TargetName ?? "", e.Timestamp, targets);
        source.TaskStarted += (_, e) => Start(Key("task", e.BuildEventContext), e.Timestamp);
        source.TaskFinished += (_, e) => Stop(Key("task", e.BuildEventContext), e.TaskName ?? "", e.Timestamp, tasks);
    }
    public void Shutdown() { }
    internal void Save(string path, string project) => File.WriteAllText(path, JsonSerializer.Serialize(new { project, requestNumber, phases, targets, tasks }, Program.Json));
}
