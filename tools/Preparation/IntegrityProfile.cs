using System.Diagnostics;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

// Opt-in instrumentation for the test bridge. Normal workflow calls do not
// collect clocks or allocation counters, and this never changes validation.
internal sealed class IntegrityProfile
{
    private readonly Dictionary<string, (double Seconds, long Bytes)> phases = new(StringComparer.Ordinal);
    public long Files { get; set; }
    public long ReusedFiles { get; set; }
    public long ReusedBytes { get; set; }
    public long ContentBytes { get; set; }
    public static (long Ticks, long Bytes) Begin() => (Stopwatch.GetTimestamp(), GC.GetAllocatedBytesForCurrentThread());
    public void End(string phase, (long Ticks, long Bytes) start)
    {
        var seconds = Stopwatch.GetElapsedTime(start.Ticks).TotalSeconds; var bytes = GC.GetAllocatedBytesForCurrentThread() - start.Bytes;
        var previous = phases.GetValueOrDefault(phase); phases[phase] = (previous.Seconds + seconds, previous.Bytes + bytes);
    }
    public JsonObject Report()
    {
        var result = new JsonObject();
        foreach (var (name, value) in phases) result[name] = new JsonObject { ["seconds"] = value.Seconds, ["allocatedBytes"] = value.Bytes };
        return new JsonObject { ["reusedFiles"] = ReusedFiles, ["reusedBytes"] = ReusedBytes, ["files"] = Files, ["contentBytes"] = ContentBytes, ["phases"] = result };
    }
}
