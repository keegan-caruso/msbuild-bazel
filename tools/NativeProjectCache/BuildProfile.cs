using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text.Json;

// Diagnostic-only timings. Nested phases overlap; never sum parent and child.
internal static class BuildProfile
{
    private static readonly ConcurrentDictionary<string, (double Seconds, int Calls)> Totals = new();
    private static bool Enabled => Environment.GetEnvironmentVariable("NATIVE_CACHE_PROFILE") is not null;
    internal static void Reset() => Totals.Clear();
    internal static IDisposable Measure(string name) => new Timing(name, Enabled);
    private sealed class Timing(string name, bool enabled) : IDisposable
    {
        private readonly long start = Stopwatch.GetTimestamp();
        public void Dispose()
        {
            if (!enabled) return;
            var seconds = Stopwatch.GetElapsedTime(start).TotalSeconds;
            Totals.AddOrUpdate(name, (seconds, 1), (_, value) => (value.Seconds + seconds, value.Calls + 1));
        }
    }
    internal static void Save(string suffix = "")
    {
        var path = Environment.GetEnvironmentVariable("NATIVE_CACHE_PROFILE");
        if (path is not null) File.WriteAllText(path + suffix, JsonSerializer.Serialize(Totals.ToDictionary(p => p.Key, p => new { seconds = p.Value.Seconds, calls = p.Value.Calls }), new JsonSerializerOptions { WriteIndented = true }));
    }
}
