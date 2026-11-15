using System.Collections.Concurrent;
using System.Text.Json;
using System.Threading.Channels;

namespace RulesMSBuild.GraphBuild;

internal sealed record WorkerInput(string Path, string Digest = "");
internal sealed record WorkerRequest(string[] Arguments, WorkerInput[] Inputs, int RequestId = 0, bool Cancel = false);
internal sealed record WorkerReply(int ExitCode, string Output, int RequestId = 0, bool WasCancelled = false);

// The input pump must remain live while the serial executor awaits a child, so
// Bazel cancellation can terminate that child rather than wait for its reply.
internal static class WorkerRequests
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    internal static async Task Run(TextReader reader, TextWriter writer,
        Func<WorkerRequest, CancellationToken, Task<WorkerReply>> execute)
    {
        var requests = Channel.CreateBounded<(WorkerRequest Work, CancellationTokenSource Stop)>(1);
        var active = new ConcurrentDictionary<int, CancellationTokenSource>();
        var cancellationGate = new object();
        using var receiving = new CancellationTokenSource();
        var input = Task.Run(Receive);
        try
        {
            await foreach (var (work, stop) in requests.Reader.ReadAllAsync())
            {
                using (stop)
                {
                    WorkerReply reply;
                    try
                    {
                        stop.Token.ThrowIfCancellationRequested();
                        reply = (await execute(work, stop.Token)) with
                        {
                            RequestId = work.RequestId
                        };
                    }
                    catch (OperationCanceledException) when (stop.IsCancellationRequested)
                    {
                        reply = new(0, "Graph request cancelled", work.RequestId, WasCancelled: true);
                    }
                    catch (Exception error)
                    {
                        reply = new(1, error.ToString(), work.RequestId);
                    }
                    finally
                    {
                        lock (cancellationGate)
                        {
                            active.TryRemove(work.RequestId, out _);
                        }
                    }
                    await writer.WriteLineAsync(JsonSerializer.Serialize(reply, Json));
                    await writer.FlushAsync();
                }
            }
            await input;
        }
        finally
        {
            receiving.Cancel();
            CancelAll();
            WorkerProcess.Observe(input);
        }

        void CancelAll()
        {
            lock (cancellationGate)
            {
                foreach (var stop in active.Values)
                {
                    stop.Cancel();
                }
            }
        }

        async Task Receive()
        {
            try
            {
                while (await reader.ReadLineAsync(receiving.Token) is { } line)
                {
                    var work = JsonSerializer.Deserialize<WorkerRequest>(line, Json) ?? throw new InvalidDataException("Missing worker request");
                    if (work.Cancel)
                    {
                        lock (cancellationGate)
                        {
                            if (active.TryGetValue(work.RequestId, out var cancellation))
                            {
                                cancellation.Cancel();
                            }
                        }
                        continue;
                    }
                    var stop = new CancellationTokenSource();
                    if (!active.TryAdd(work.RequestId, stop))
                    {
                        stop.Dispose();
                        throw new InvalidDataException("Duplicate active graph request ID");
                    }
                    try
                    {
                        if (!requests.Writer.TryWrite((work, stop)))
                        {
                            throw new InvalidDataException("Graph worker accepts at most one queued request");
                        }
                    }
                    catch
                    {
                        lock (cancellationGate)
                        {
                            active.TryRemove(work.RequestId, out _);
                            stop.Dispose();
                        }
                        throw;
                    }
                }
                requests.Writer.TryComplete();
            }
            catch (Exception error)
            {
                CancelAll();
                requests.Writer.TryComplete(error);
            }
        }
    }
}
