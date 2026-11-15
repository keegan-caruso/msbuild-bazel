#!/usr/bin/env python3
"""Native fake-child controls for worker supervision; no Linux sandbox required."""

from pathlib import Path
import tempfile
from qualify import DOTNET, ROOT, run


def main():
    with tempfile.TemporaryDirectory(prefix='worker-supervision-') as temporary:
        work = Path(temporary)
        sources = ''.join(f'<Compile Include="{ROOT / "tools/GraphBuild" / name}" />'
                          for name in ['WorkerProcess.cs', 'WorkerOutput.cs', 'RetainedGraphProcess.cs', 'WorkerRequests.cs'])
        (work / 'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework>'
            '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
            '<TreatWarningsAsErrors>true</TreatWarningsAsErrors></PropertyGroup>'
            f'<ItemGroup>{sources}</ItemGroup></Project>')
        (work / 'Program.cs').write_text(r'''
using System.Diagnostics;
using System.Text.Json;
using RulesMSBuild.GraphBuild;

if (args.Length > 0)
{
    var mode = args[0];
    if (mode == "grandchild") { await Task.Delay(Timeout.Infinite); return; }
    if (mode == "hang")
    {
        using var child = Process.Start(Start("grandchild"))!;
        File.WriteAllText(args[1], Environment.ProcessId + "," + child.Id);
        await Task.Delay(Timeout.Infinite);
        return;
    }
    if (mode == "noise")
    {
        Console.Out.Write(new string('x', WorkerProcess.OutputCharacters * 3));
        Console.Error.Write(new string('y', WorkerProcess.OutputCharacters * 3));
        return;
    }
    if (mode == "exit") { Environment.Exit(17); }
    while (Console.ReadLine() is not null)
    {
        if (mode == "engine-hang") { await Task.Delay(Timeout.Infinite); }
        if (mode == "oversize") { Console.Write(new string('x', WorkerProcess.OutputCharacters * 7)); Console.Out.Flush(); await Task.Delay(Timeout.Infinite); }
        if (mode == "malformed") { Console.WriteLine("not-json"); return; }
        if (mode == "engine-noise") { Console.Error.Write(new string('z', WorkerProcess.OutputCharacters * 3)); }
        Console.WriteLine(JsonSerializer.Serialize(new EngineReply(0, "ok")));
    }
    return;
}

ProcessStartInfo Start(string mode, string? path = null)
{
    var start = new ProcessStartInfo(Environment.ProcessPath!)
    {
        RedirectStandardOutput = true, RedirectStandardError = true,
    };
    start.ArgumentList.Add(typeof(EngineRequest).Assembly.Location);
    start.ArgumentList.Add(mode);
    if (path is not null) { start.ArgumentList.Add(path); }
    return start;
}

void Check(bool condition, string message) { if (!condition) { throw new Exception(message); } }

async Task Expect<T>(Func<Task> action) where T : Exception
{
    try { await action(); } catch (T) { return; }
    throw new Exception("Expected " + typeof(T).Name);
}

void CheckExited(string path)
{
    Check(File.Exists(path), "Child did not start");
    foreach (var pid in File.ReadAllText(path).Split(',').Select(int.Parse))
    {
        try { using var process = Process.GetProcessById(pid); Check(process.WaitForExit(5000), "Leaked child " + pid); }
        catch (ArgumentException) { }
    }
    File.Delete(path);
}

var noise = await WorkerProcess.RunAsync(Start("noise"));
Check(noise.ExitCode == 0 && noise.Output.Length < WorkerProcess.OutputCharacters + 128 && noise.Output.Contains("output truncated"), "Unbounded output or drain deadlock");
Check((await WorkerProcess.RunAsync(Start("exit"))).ExitCode == 17, "Lost child exit status");
var pids = Path.Combine(Path.GetTempPath(), "worker-process-" + Guid.NewGuid() + ".pids");
await Expect<TimeoutException>(() => WorkerProcess.RunAsync(Start("hang", pids), timeout: TimeSpan.FromSeconds(1)));
CheckExited(pids);
using (var stop = new CancellationTokenSource(1000))
{
    await Expect<OperationCanceledException>(() => WorkerProcess.RunAsync(Start("hang", pids), stop.Token));
}
CheckExited(pids);
foreach (var mode in new[] { "malformed", "oversize", "engine-hang" })
{
    using var engine = new RetainedGraphProcess(Start(mode));
    await Expect<Exception>(() => engine.Run(new("Build", false, 512), timeout: TimeSpan.FromSeconds(2)));
}
using (var engine = new RetainedGraphProcess(Start("engine-hang")))
using (var stop = new CancellationTokenSource(1000))
{
    await Expect<OperationCanceledException>(() => engine.Run(new("Build", false, 512), stop.Token));
}
using (var engine = new RetainedGraphProcess(Start("engine-noise")))
{
    Check((await engine.Run(new("Build", false, 512))).Output == "ok", "Noisy engine first reply failed");
    Check((await engine.Run(new("Build", false, 512))).Output == "ok", "Noisy engine reuse failed");
}
using (var engine = new RetainedGraphProcess(Start("ok")))
{
    Check((await engine.Run(new("Build", false, 512))).ExitCode == 0, "Fresh engine recovery failed");
}
var messages = new Messages();
using var replies = new StringWriter();
var began = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
var recovered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
var dispatch = WorkerRequests.Run(messages, replies, async (request, cancellation) =>
{
    if (request.RequestId == 1)
    {
        began.SetResult();
        await Task.Delay(Timeout.Infinite, cancellation);
    }
    recovered.SetResult();
    return new WorkerReply(0, "recovered");
});
messages.Send("{\"arguments\":[\"unused\"],\"inputs\":[],\"requestId\":1}");
await began.Task.WaitAsync(TimeSpan.FromSeconds(5));
messages.Send("{\"requestId\":1,\"cancel\":true}");
messages.Send("{\"arguments\":[\"unused\"],\"inputs\":[],\"requestId\":2}");
await recovered.Task.WaitAsync(TimeSpan.FromSeconds(5));
messages.Complete();
await dispatch.WaitAsync(TimeSpan.FromSeconds(5));
var responses = replies.ToString().Split('\n', StringSplitOptions.RemoveEmptyEntries).Select(line => JsonDocument.Parse(line)).ToArray();
Check(responses.Length == 2 && responses[0].RootElement.GetProperty("wasCancelled").GetBoolean()
    && responses[1].RootElement.GetProperty("requestId").GetInt32() == 2, "Cancellation dispatch or recovery failed");
var overloaded = new Messages();
using var overloadReplies = new StringWriter();
var occupied = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
var overload = WorkerRequests.Run(overloaded, overloadReplies, async (request, cancellation) =>
{
    occupied.TrySetResult();
    await Task.Delay(Timeout.Infinite, cancellation);
    return new WorkerReply(0, "unused");
});
overloaded.Send("{\"arguments\":[],\"inputs\":[],\"requestId\":10}");
await occupied.Task.WaitAsync(TimeSpan.FromSeconds(5));
overloaded.Send("{\"arguments\":[],\"inputs\":[],\"requestId\":11}");
overloaded.Send("{\"arguments\":[],\"inputs\":[],\"requestId\":12}");
await Expect<InvalidDataException>(() => overload.WaitAsync(TimeSpan.FromSeconds(5)));
Console.WriteLine("PASS: bounded noisy output, exit status, active deadline, cancellation, child-tree cleanup, malformed/oversized replies, noisy retained reuse, fresh recovery and live request cancellation/retry and bounded queue admission");

namespace RulesMSBuild.GraphBuild
{
    internal sealed class Messages : TextReader
    {
        private readonly System.Threading.Channels.Channel<string> lines = System.Threading.Channels.Channel.CreateUnbounded<string>();
        internal void Send(string line) => lines.Writer.TryWrite(line);
        internal void Complete() => lines.Writer.Complete();
        public override async ValueTask<string?> ReadLineAsync(CancellationToken cancellationToken)
        {
            return await lines.Reader.WaitToReadAsync(cancellationToken) ? await lines.Reader.ReadAsync(cancellationToken) : null;
        }
    }
    internal sealed record EngineRequest(string Target, bool ProfileBuild, int EvaluationCacheMb);
    internal sealed record EngineReply(int ExitCode, string Output, bool Restart = false, bool Retire = false,
        long ManagedBytes = 0, long ResidentBytes = 0);
}
''')
        run(DOTNET, 'build', work / 'Probe.csproj', '-c', 'Release')
        print(run(DOTNET, work / 'bin/Release/net10.0/Probe.dll').stdout, end='')


if __name__ == '__main__':
    main()
