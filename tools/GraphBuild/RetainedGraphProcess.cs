using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text.Json;

namespace RulesMSBuild.GraphBuild;

// Keep the thread that creates bubblewrap alive for the entire engine lifetime:
// Linux parent-death signalling follows that thread, not merely the parent PID.
internal sealed class RetainedGraphProcess : IDisposable
{
    private sealed record Command(EngineRequest Request, TaskCompletionSource<EngineReply> Completion);
    private readonly BlockingCollection<Command> commands = new();
    private readonly Thread thread;
    private Process? process;
    private Exception? failure;

    internal RetainedGraphProcess(ProcessStartInfo start)
    {
        start.RedirectStandardInput = true;
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = true;
        thread = new Thread(() => Serve(start)) { IsBackground = true, Name = "MSBuild sandbox lifetime" };
        thread.Start();
    }

    internal async Task<EngineReply> Run(EngineRequest request)
    {
        if (failure is not null)
        {
            throw new IOException("Retained graph engine failed", failure);
        }
        var completion = new TaskCompletionSource<EngineReply>(TaskCreationOptions.RunContinuationsAsynchronously);
        commands.Add(new(request, completion));
        return await completion.Task;
    }

    private void Serve(ProcessStartInfo start)
    {
        Command? current = null;
        try
        {
            using var child = Process.Start(start) ?? throw new IOException("Cannot start retained graph sandbox");
            process = child;
            var stderr = child.StandardError.ReadToEndAsync();
            foreach (var command in commands.GetConsumingEnumerable())
            {
                current = command;
                child.StandardInput.WriteLine(JsonSerializer.Serialize(command.Request));
                child.StandardInput.Flush();
                var line = child.StandardOutput.ReadLine();
                if (line is null)
                {
                    child.WaitForExit();
                    throw new IOException("Retained graph engine exited: " + stderr.GetAwaiter().GetResult());
                }
                var reply = JsonSerializer.Deserialize<EngineReply>(line) ?? throw new InvalidDataException("Missing engine reply");
                command.Completion.SetResult(reply);
                current = null;
                if (reply.Restart || reply.Retire)
                {
                    break;
                }
            }
            child.StandardInput.Close();
            if (!child.WaitForExit(5000))
            {
                child.Kill(entireProcessTree: true);
                child.WaitForExit();
            }
            stderr.GetAwaiter().GetResult();
        }
        catch (Exception error)
        {
            failure = error;
            current?.Completion.TrySetException(error);
            while (commands.TryTake(out var command))
            {
                command.Completion.TrySetException(error);
            }
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

    public void Dispose()
    {
        commands.CompleteAdding();
        if (!thread.Join(10000))
        {
            try
            {
                process?.Kill(entireProcessTree: true);
            }
            catch (InvalidOperationException)
            {
                // It already exited while the broker was shutting down.
            }
            thread.Join();
        }
        commands.Dispose();
    }
}
