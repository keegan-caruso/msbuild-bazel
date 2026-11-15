using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace RulesMSBuild.GraphBuild;

// Keep the thread that creates bubblewrap alive for the entire engine lifetime:
// Linux parent-death signalling follows that thread, not merely the parent PID.
internal sealed class RetainedGraphProcess : IDisposable
{
    private sealed record Command(EngineRequest Request, TaskCompletionSource<EngineReply> Completion);
    private readonly BlockingCollection<Command> commands = new();
    private readonly CancellationTokenSource stopped = new();
    private readonly Thread thread;
    private volatile Exception? failure;

    internal RetainedGraphProcess(ProcessStartInfo start)
    {
        start.RedirectStandardInput = true;
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = true;
        thread = new Thread(() => Serve(start)) { IsBackground = true, Name = "MSBuild sandbox lifetime" };
        thread.Start();
    }

    internal async Task<EngineReply> Run(EngineRequest request, CancellationToken cancellationToken = default,
        TimeSpan? timeout = null)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (failure is not null || commands.IsAddingCompleted)
        {
            throw new IOException("Retained graph engine stopped", failure);
        }
        var completion = new TaskCompletionSource<EngineReply>(TaskCreationOptions.RunContinuationsAsynchronously);
        try
        {
            commands.Add(new(request, completion), cancellationToken);
            return await completion.Task.WaitAsync(timeout ?? WorkerProcess.RequestTimeout, cancellationToken);
        }
        catch (Exception error) when (error is TimeoutException or OperationCanceledException)
        {
            failure = error;
            stopped.Cancel();
            WorkerProcess.Observe(completion.Task);
            throw;
        }
    }

    private void Serve(ProcessStartInfo start)
    {
        Command? current = null;
        try
        {
            stopped.Token.ThrowIfCancellationRequested();
            using var child = Process.Start(start) ?? throw new IOException("Cannot start retained graph sandbox");
            using var terminate = stopped.Token.Register(() =>
            {
                var terminationFailure = WorkerProcess.Terminate(child);
                if (terminationFailure is not null)
                {
                    failure = terminationFailure;
                }
            });
            using var errors = new WorkerOutput();
            using var drain = new CancellationTokenSource();
            var stderr = errors.DrainAsync(child.StandardError, drain.Token);
            try
            {
                foreach (var command in commands.GetConsumingEnumerable(stopped.Token))
                {
                    current = command;
                    child.StandardInput.WriteLine(JsonSerializer.Serialize(command.Request));
                    child.StandardInput.Flush();
                    var line = ReadReply(child.StandardOutput);
                    if (line is null)
                    {
                        throw new IOException("Retained graph engine exited: " + errors);
                    }
                    var reply = JsonSerializer.Deserialize<EngineReply>(line) ?? throw new InvalidDataException("Missing engine reply");
                    if (reply.Output.Length > WorkerProcess.OutputCharacters + 128)
                    {
                        throw new InvalidDataException("Retained graph engine output exceeds diagnostic budget");
                    }
                    command.Completion.TrySetResult(reply);
                    current = null;
                    if (reply.Restart || reply.Retire)
                    {
                        break;
                    }
                }
            }
            finally
            {
                var terminationFailure = WorkerProcess.Terminate(child);
                drain.Cancel();
                WorkerProcess.Observe(stderr);
                if (terminationFailure is not null)
                {
                    throw new IOException("Retained graph sandbox termination failed", terminationFailure);
                }
            }
        }
        catch (Exception error)
        {
            failure ??= error;
            current?.Completion.TrySetException(failure);
        }
        finally
        {
            commands.CompleteAdding();
            while (commands.TryTake(out var command))
            {
                command.Completion.TrySetException(failure ?? new IOException("Retained graph engine stopped"));
            }
        }
    }

    private static string? ReadReply(StreamReader reader)
    {
        // JSON can escape one diagnostic character as six wire characters. Read
        // through StreamReader's buffer without allocating an unbounded line.
        const int limit = WorkerProcess.OutputCharacters * 6 + 4096;
        var line = new StringBuilder();
        int value;
        while ((value = reader.Read()) != -1)
        {
            if (value == '\n')
            {
                return line.ToString();
            }
            if (line.Length == limit)
            {
                throw new InvalidDataException("Retained graph engine reply exceeds protocol budget");
            }
            line.Append((char)value);
        }
        return line.Length == 0 ? null : throw new InvalidDataException("Incomplete retained graph engine reply");
    }

    public void Dispose()
    {
        commands.CompleteAdding();
        stopped.Cancel();
        if (!thread.Join(10000))
        {
            throw new IOException("Retained graph engine supervisor did not stop", failure);
        }
        commands.Dispose();
        stopped.Dispose();
    }
}
