using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Text;
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
                    await using var file = new FileStream(Path.ChangeExtension(output, ".bin.gz"), FileMode.CreateNew, FileAccess.Write);
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
        await using var file = File.OpenRead(Path.ChangeExtension(output, ".bin.gz"));
        await using var gzip = new GZipStream(file, CompressionMode.Decompress);
        await using var summary = new StreamWriter(new FileStream(output, FileMode.CreateNew, FileAccess.Write));
        while (ReadVarint(gzip, allowEnd: true) is { } length)
        {
            if (length > 256 * 1024 * 1024) throw new InvalidDataException("Execution record exceeds 256 MiB");
            var bytes = new byte[(int)length]; gzip.ReadExactly(bytes);
            await summary.WriteLineAsync(Action(bytes).ToJsonString());
        }
    }

    // Select the validation fields from pinned Bazel 8.4.2 SpawnExec (spawn.proto).
    // The complete length-delimited protobuf stream is preserved in the gzip file.
    private static JsonObject Action(byte[] bytes)
    {
        using var record = new MemoryStream(bytes, writable: false);
        var arguments = new JsonArray();
        var result = new JsonObject { ["commandArgs"] = arguments, ["cacheHit"] = false, ["exitCode"] = 0 };
        while (ReadVarint(record, allowEnd: true) is { } tag)
        {
            var field = tag >> 3; var wire = tag & 7;
            if (field == 0) throw new InvalidDataException("Invalid execution field");
            if (wire == 0)
            {
                var value = ReadVarint(record)!.Value;
                if (field == 13) result["cacheHit"] = value != 0;
                if (field == 15) result["exitCode"] = unchecked((int)value);
            }
            else if (wire == 2)
            {
                var length = ReadVarint(record)!.Value;
                if (length > (ulong)(record.Length - record.Position)) throw new InvalidDataException("Truncated execution field");
                if (field is 1 or 10 or 12 or 14 or 18)
                {
                    var value = new UTF8Encoding(false, true).GetString(bytes, (int)record.Position, (int)length);
                    if (field == 1) arguments.Add(value);
                    else result[field switch { 10 => "mnemonic", 12 => "runner", 14 => "status", _ => "targetLabel" }] = value;
                }
                record.Position += (long)length;
            }
            else if (wire is 1 or 5)
            {
                var length = wire == 1 ? 8 : 4;
                if (length > record.Length - record.Position) throw new InvalidDataException("Truncated execution field");
                record.Position += length;
            }
            else throw new InvalidDataException("Unsupported execution wire type");
            if ((field is 1 or 10 or 12 or 14 or 18) && wire != 2 || (field is 13 or 15) && wire != 0)
                throw new InvalidDataException("Invalid execution field type");
        }
        return result;
    }

    private static ulong? ReadVarint(Stream stream, bool allowEnd = false)
    {
        ulong value = 0;
        for (var shift = 0; shift < 70; shift += 7)
        {
            var next = stream.ReadByte();
            if (next < 0) { if (shift == 0 && allowEnd) return null; throw new InvalidDataException("Truncated execution varint"); }
            if (shift == 63 && next > 1) throw new InvalidDataException("Overflowed execution varint");
            value |= (ulong)(next & 127) << shift;
            if (next < 128) return value;
        }
        throw new InvalidDataException("Invalid execution varint");
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
