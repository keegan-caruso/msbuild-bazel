using System.Text;

namespace RulesMSBuild.GraphBuild;

// Keep draining pipes after the diagnostic budget is exhausted. Blocking a writer
// would otherwise turn a noisy build into a deadlock.
internal sealed class WorkerOutput(int limit = WorkerProcess.OutputCharacters) : TextWriter
{
    private readonly StringBuilder text = new();
    private readonly object gate = new();
    private bool truncated;
    public override Encoding Encoding => Encoding.UTF8;

    public override void Write(char value)
    {
        lock (gate)
        {
            if (text.Length < limit)
            {
                text.Append(value);
            }
            else
            {
                truncated = true;
            }
        }
    }

    public override void Write(string? value)
    {
        if (value is null)
        {
            return;
        }
        lock (gate)
        {
            var count = Math.Min(value.Length, limit - text.Length);
            text.Append(value, 0, count);
            truncated |= count != value.Length;
        }
    }

    public override void Write(char[] buffer, int index, int count) => Write(buffer.AsSpan(index, count));

    public override void Write(ReadOnlySpan<char> buffer)
    {
        lock (gate)
        {
            var count = Math.Min(buffer.Length, limit - text.Length);
            text.Append(buffer[..count]);
            truncated |= count != buffer.Length;
        }
    }

    public override string ToString()
    {
        lock (gate)
        {
            return text.ToString() + (truncated ? "\n[graph worker output truncated]\n" : "");
        }
    }

    internal async Task DrainAsync(StreamReader reader, CancellationToken cancellationToken)
    {
        var buffer = new char[8192];
        int count;
        while ((count = await reader.ReadAsync(buffer.AsMemory(), cancellationToken)) != 0)
        {
            Write(buffer.AsSpan(0, count));
        }
    }
}
