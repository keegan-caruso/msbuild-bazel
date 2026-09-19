using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Win32.SafeHandles;

namespace RulesMSBuild.Preparation;

// Keep the full Bazel trace compressed on disk, with only small action records in memory.
internal sealed class ExecutionTrace : IDisposable
{
    private readonly string directory;
    private readonly string output;
    private readonly SafeFileHandle keepAlive;
    private readonly Task capture;
    private bool completed;
    public string Pipe { get; }

    public ExecutionTrace(string output)
    {
        this.output = output;
        directory = Directory.CreateTempSubdirectory("msbuild-trace-").FullName;
        Pipe = Path.Combine(directory, "trace");
        if (Mkfifo(Pipe, 384) != 0) { Directory.Delete(directory); throw new IOException("Cannot create execution trace pipe", new System.ComponentModel.Win32Exception(Marshal.GetLastPInvokeError())); }
        // Set close-on-exec atomically: Bazel may start a persistent server.
        var descriptor = Open(Pipe, 2 | (OperatingSystem.IsMacOS() ? 0x1000000 : 0x80000));
        if (descriptor < 0) { File.Delete(Pipe); Directory.Delete(directory); throw new IOException("Cannot open execution trace pipe"); }
        keepAlive = new SafeFileHandle((IntPtr)descriptor, true);
        // Open the reader before starting the writer; the keepalive prevents premature EOF.
        var input = new FileStream(Pipe, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        capture = Task.Run(async () =>
        {
            using (input)
            {
                try
                {
                    await using var file = new FileStream(output + ".gz", FileMode.CreateNew, FileAccess.Write);
                    await using var gzip = new GZipStream(file, CompressionLevel.Fastest);
                    await input.CopyToAsync(gzip);
                }
                catch
                {
                    // A full disk must fail reporting without leaving Bazel blocked on its pipe.
                    await input.CopyToAsync(Stream.Null);
                    throw;
                }
            }
        });
    }

    public void Complete()
    {
        if (completed) return;
        completed = true;
        keepAlive.Dispose();
        capture.GetAwaiter().GetResult();
        Summarize().GetAwaiter().GetResult();
    }

    private async Task Summarize()
    {
        await using var file = File.OpenRead(output + ".gz");
        await using var gzip = new GZipStream(file, CompressionMode.Decompress);
        await using var summary = new StreamWriter(new FileStream(output, FileMode.CreateNew, FileAccess.Write));
        await foreach (var node in JsonSerializer.DeserializeAsyncEnumerable<JsonObject>(gzip, topLevelValues: true))
        {
            if (node is null) throw new InvalidDataException("Null execution trace record");
            // These arrays dominate large-graph logs. The original is retained verbatim in gzip.
            node.Remove("inputs"); node.Remove("listedOutputs"); node.Remove("actualOutputs");
            await summary.WriteLineAsync(node.ToJsonString());
        }
    }

    public void Dispose()
    {
        try { Complete(); }
        finally { keepAlive.Dispose(); File.Delete(Pipe); Directory.Delete(directory); }
    }

    [DllImport("libc", EntryPoint = "mkfifo", SetLastError = true)]
    private static extern int Mkfifo(string path, uint mode);
    [DllImport("libc", EntryPoint = "open", SetLastError = true)]
    private static extern int Open(string path, int flags);
}
