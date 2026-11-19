using System.Text;

namespace RulesMSBuild.GraphBuild;

// Keep draining pipes after the diagnostic budget is exhausted. Blocking a writer
// would otherwise turn a noisy build into a deadlock.
internal sealed class WorkerOutput(int limit = WorkerProcess.OutputCharacters) : TextWriter
{
    private readonly char[] text = new char[limit];
    private readonly Lock gate = new();
    private int position;
    private int length;
    private bool truncated;
    public override Encoding Encoding => Encoding.UTF8;

    public override void Write(char value)
    {
        Span<char> character = stackalloc char[1];
        character[0] = value;
        Write(character);
    }

    public override void Write(string? value)
    {
        if (value is not null)
        {
            Write(value.AsSpan());
        }
    }

    public override void Write(char[] buffer, int index, int count) => Write(buffer.AsSpan(index, count));

    public override void Write(ReadOnlySpan<char> buffer)
    {
        lock (gate)
        {
            truncated |= buffer.Length > limit - length;
            if (buffer.Length >= limit)
            {
                buffer[^limit..].CopyTo(text);
                position = 0;
                length = limit;
                return;
            }
            var first = Math.Min(buffer.Length, limit - position);
            buffer[..first].CopyTo(text.AsSpan(position));
            buffer[first..].CopyTo(text);
            position = (position + buffer.Length) % limit;
            length = Math.Min(limit, length + buffer.Length);
        }
    }

    public override string ToString()
    {
        lock (gate)
        {
            if (!truncated)
            {
                return new string(text, 0, length);
            }
            return "[graph worker output truncated; showing tail]\n" +
                new string(text, position, limit - position) + new string(text, 0, position);
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
