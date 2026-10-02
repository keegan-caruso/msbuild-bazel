using System.Diagnostics;

namespace RulesMSBuild.GraphBuild;

internal static class WorkerProcess
{
    internal static Task<(int ExitCode, string Output)> RunAsync(ProcessStartInfo start) => Task.Factory.StartNew(() =>
    {
        // Linux parent-death signals track the creating thread. Keep that thread
        // alive until bubblewrap exits, rather than launching from a retiring
        // thread-pool thread. Output readers remain asynchronous to drain pipes.
        using var child = Process.Start(start) ?? throw new IOException("Cannot start graph sandbox");
        var stdout = child.StandardOutput.ReadToEndAsync();
        var stderr = child.StandardError.ReadToEndAsync();
        child.WaitForExit();
        return (child.ExitCode, stdout.GetAwaiter().GetResult() + stderr.GetAwaiter().GetResult());
    }, CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
}
