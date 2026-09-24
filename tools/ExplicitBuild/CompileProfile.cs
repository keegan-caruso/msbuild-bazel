using System.Diagnostics;
using System.Text.Json;
using Microsoft.Build.Framework;

// Opt-in diagnostics. Target/task totals are inclusive and must not be added
// to phase wall time (MSBuild tasks may invoke nested targets).
internal sealed class CompileProfile : ILogger
{
    private sealed record Sample(double WallSeconds, double CpuSeconds);
    private sealed class Aggregate
    {
        public int Count
        {
            get; set;
        }
        public double Seconds
        {
            get; set;
        }
    }
    private readonly List<object> evaluations = new();
    private readonly List<string> compilerMessages = new();
    private readonly HashSet<string> compilerTasks = new(StringComparer.Ordinal);
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
    public string? Parameters
    {
        get; set;
    }
    internal void Mark(string name)
    {
        var now = clock.Elapsed.TotalSeconds;
        var processor = Process.GetCurrentProcess().TotalProcessorTime;
        phases.Add(name, new(now - last, (processor - cpu).TotalSeconds));
        last = now;
        cpu = processor;
    }
    private static string Key(string kind, BuildEventContext? c) => $"{kind}:{c?.SubmissionId}:{c?.NodeId}:{c?.ProjectContextId}:{c?.TargetId}:{c?.TaskId}";
    private void Start(string key, DateTime time)
    {
        lock (gate)
        {
            starts[key] = time;
        }
    }
    private void Stop(string key, string name, DateTime time, Dictionary<string, Aggregate> totals)
    {
        lock (gate)
        {
            if (!starts.Remove(key, out var start))
            {
                return;
            }

            if (!totals.TryGetValue(name, out var total))
            {
                totals.Add(name, total = new());
            }

            total.Count++;
            total.Seconds += (time - start).TotalSeconds;
        }
    }
    public void Initialize(IEventSource source)
    {
        source.AnyEventRaised += (_, e) =>
        {
            if (e is not ProjectEvaluationFinishedEventArgs { ProfilerResult: { } result })
            {
                return;
            }

            var rows = result.ProfiledLocations;
            lock (gate)
            {
                evaluations.Add(new
                {
                    passes = rows.Where(p => p.Key.IsEvaluationPass).Select(p => new { pass = p.Key.EvaluationPass.ToString(), p.Key.EvaluationPassDescription, inclusiveSeconds = p.Value.InclusiveTime.TotalSeconds, exclusiveSeconds = p.Value.ExclusiveTime.TotalSeconds }).ToArray(),
                    files = rows.Where(p => p.Key.File is not null).GroupBy(p => p.Key.File).Select(g => new { file = g.Key, exclusiveSeconds = g.Sum(p => p.Value.ExclusiveTime.TotalSeconds), hits = g.Sum(p => p.Value.NumberOfHits) }).OrderByDescending(p => p.exclusiveSeconds).ToArray(),
                    hotspots = rows.Where(p => p.Key.File is not null).OrderByDescending(p => p.Value.ExclusiveTime).Take(30).Select(p => new { p.Key.File, p.Key.Line, p.Key.ElementName, p.Key.ElementDescription, kind = p.Key.Kind.ToString(), exclusiveSeconds = p.Value.ExclusiveTime.TotalSeconds, p.Value.NumberOfHits }).ToArray(),
                });
            }
        };
        source.TargetStarted += (_, e) => Start(Key("target", e.BuildEventContext), e.Timestamp);
        source.TargetFinished += (_, e) => Stop(Key("target", e.BuildEventContext), e.TargetName ?? "", e.Timestamp, targets);
        source.TaskStarted += (_, e) =>
        {
            Start(Key("task", e.BuildEventContext), e.Timestamp);
            if (e.TaskName is "Csc" or "Vbc")
            {
                lock (gate)
                {
                    compilerTasks.Add(Key("task", e.BuildEventContext));
                }
            }
        };
        source.MessageRaised += (_, e) =>
        {
            // ReportAnalyzer emits low-importance messages that the normal build
            // log omits. Keep diagnostic text only while a compiler task is active.
            if (e is TaskCommandLineEventArgs || e.Message is not { Length: > 0 and <= 4096 } message)
            {
                return;
            }
            lock (gate)
            {
                if (compilerTasks.Contains(Key("task", e.BuildEventContext)))
                {
                    compilerMessages.Add(message);
                }
            }
        };
        source.TaskFinished += (_, e) =>
        {
            Stop(Key("task", e.BuildEventContext), e.TaskName ?? "", e.Timestamp, tasks);
            lock (gate)
            {
                compilerTasks.Remove(Key("task", e.BuildEventContext));
            }
        };
    }
    public void Shutdown()
    {
    }
    internal void Save(string path, string project) => File.WriteAllText(path, JsonSerializer.Serialize(new { project, requestNumber, phases, targets, tasks, evaluations, compilerMessages }, Program.Json));
}
