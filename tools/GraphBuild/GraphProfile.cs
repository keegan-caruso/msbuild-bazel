using System.Collections.Concurrent;
using System.Diagnostics;

namespace RulesMSBuild.GraphBuild;

// Opt-in operation totals can overlap across threads and nested scopes.
internal static class GraphProfile
{
    internal static bool Enabled
    {
        get; set;
    }
    private static readonly ConcurrentDictionary<string, Metric> Metrics = new(StringComparer.Ordinal);
    internal static object? Report => Enabled ? Metrics.OrderBy(pair => pair.Key, StringComparer.Ordinal).ToDictionary(
        pair => pair.Key, pair => new { seconds = (double)pair.Value.Ticks / Stopwatch.Frequency, calls = pair.Value.Calls, bytes = pair.Value.Bytes }) : null;

    internal static IDisposable? Measure(string name, long bytes = 0) => Enabled ? new Scope(Metrics.GetOrAdd(name, _ => new Metric()), bytes) : null;

    private sealed class Metric
    {
        internal long Ticks;
        internal long Calls;
        internal long Bytes;
    }

    private sealed class Scope(Metric metric, long bytes) : IDisposable
    {
        private readonly long start = Stopwatch.GetTimestamp();
        public void Dispose()
        {
            Interlocked.Add(ref metric.Ticks, Stopwatch.GetTimestamp() - start);
            Interlocked.Increment(ref metric.Calls);
            Interlocked.Add(ref metric.Bytes, bytes);
        }
    }
}
