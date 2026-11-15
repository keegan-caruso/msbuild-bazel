using System.Diagnostics;

namespace RulesMSBuild.GraphBuild;

internal static class WorkerProcess
{
    internal const int OutputCharacters = 1024 * 1024;
    internal static readonly TimeSpan RequestTimeout = TimeSpan.FromHours(1);
    private static readonly TimeSpan CleanupTimeout = TimeSpan.FromSeconds(5);

    internal static Task<(int ExitCode, string Output)> RunAsync(ProcessStartInfo start,
        CancellationToken cancellationToken = default, TimeSpan? timeout = null) => Task.Factory.StartNew(() =>
    {
        // Linux parent-death signals track the creating thread. Keep that thread
        // alive until bubblewrap exits, rather than launching from a retiring
        // thread-pool thread. Output readers remain asynchronous to drain pipes.
        cancellationToken.ThrowIfCancellationRequested();
        using var child = Process.Start(start) ?? throw new IOException("Cannot start graph sandbox");
        using var deadline = new CancellationTokenSource(timeout ?? RequestTimeout);
        using var stop = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, deadline.Token);
        using var terminate = stop.Token.Register(() => Terminate(child));
        using var output = new WorkerOutput();
        using var drain = new CancellationTokenSource();
        var readers = Task.WhenAll(output.DrainAsync(child.StandardOutput, drain.Token), output.DrainAsync(child.StandardError, drain.Token));
        try
        {
            child.WaitForExitAsync(stop.Token).GetAwaiter().GetResult();
            readers.WaitAsync(CleanupTimeout, stop.Token).GetAwaiter().GetResult();
            return (child.ExitCode, output.ToString());
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested && deadline.IsCancellationRequested)
        {
            throw new TimeoutException("Graph sandbox exceeded its request deadline. " + output);
        }
        finally
        {
            var terminationFailure = Terminate(child);
            drain.Cancel();
            Observe(readers);
            if (terminationFailure is not null)
            {
                throw new IOException("Graph sandbox termination failed", terminationFailure);
            }
        }
    }, CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);

    internal static Exception? Terminate(Process child)
    {
        try
        {
            if (!child.HasExited)
            {
                child.Kill(entireProcessTree: true);
            }
            if (!child.WaitForExit((int)CleanupTimeout.TotalMilliseconds))
            {
                return new IOException("Graph sandbox did not exit after termination");
            }
        }
        catch (InvalidOperationException)
        {
            // Disposal or normal exit may race cancellation.
        }
        catch (Exception error)
        {
            // Cancellation callbacks also run on timer threads. Never let a
            // termination error escape there and crash the worker process.
            return error;
        }
        return null;
    }

    internal static void Observe(Task task) => _ = task.ContinueWith(completed => _ = completed.Exception,
        CancellationToken.None, TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
}
