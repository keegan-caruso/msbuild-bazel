using System.Diagnostics;
using System.Text.Json;

namespace RulesMSBuild.ProjectSync;

// Diagnostics are opt-in. Nested phase times overlap; never use them as scores.
internal static class SyncProfile
{
    internal static IDisposable? Measure(string phase) => Environment.GetEnvironmentVariable("RULES_MSBUILD_SYNC_PROFILE") == "1" ? new Scope(phase) : null;

    internal static T Run<T>(string phase, Func<T> operation)
    {
        using var scope = Measure(phase);
        return operation();
    }

    private sealed class Scope(string phase) : IDisposable
    {
        private readonly Stopwatch timer = Stopwatch.StartNew();

        public void Dispose() => Console.Error.WriteLine("PROJECT_SYNC_PROFILE " + JsonSerializer.Serialize(new { phase, seconds = timer.Elapsed.TotalSeconds }));
    }
}
