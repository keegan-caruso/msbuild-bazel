using System.Diagnostics;

namespace ActionRunner;

internal sealed record ProcessResult(int ExitCode, string StandardOutput, string StandardError, bool TimedOut)
{
    public string Log => StandardOutput + StandardError;
}

internal static class ProcessRunner
{
    public static async Task<ProcessResult> RunAsync(ProcessStartInfo start, TimeSpan timeout,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        using var process = new Process { StartInfo = start };
        process.Start();
        // Drain both pipes concurrently so a full stderr buffer cannot block the child.
        var output = process.StandardOutput.ReadToEndAsync();
        var error = process.StandardError.ReadToEndAsync();
        var completion = Task.WhenAll(process.WaitForExitAsync(), output, error);
        using var deadline = new CancellationTokenSource(timeout);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(deadline.Token, cancellationToken);
        var timedOut = false;
        try
        {
            await completion.WaitAsync(linked.Token);
        }
        catch (OperationCanceledException)
        {
            timedOut = deadline.IsCancellationRequested;
            try { process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) when (process.HasExited) { }
            await completion;
            cancellationToken.ThrowIfCancellationRequested();
        }
        return new ProcessResult(process.ExitCode, await output, await error, timedOut);
    }
}
