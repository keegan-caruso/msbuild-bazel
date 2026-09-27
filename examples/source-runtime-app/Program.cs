using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

// Ordinary framework APIs exercise managed and native source-built components.
var message = JsonSerializer.Deserialize<Message>("{\"Text\":\"Hello from source-built .NET\"}")!;
var bytes = Encoding.UTF8.GetBytes(message.Text);
using var compressed = new MemoryStream();
using (var gzip = new GZipStream(compressed, CompressionLevel.Fastest, leaveOpen: true))
{
    gzip.Write(bytes);
}
compressed.Position = 0;
using var reader = new StreamReader(new GZipStream(compressed, CompressionMode.Decompress));
if (await reader.ReadToEndAsync() != message.Text)
{
    throw new InvalidOperationException("Compression round trip failed");
}
Console.WriteLine(message.Text);
Console.WriteLine("SHA256=" + Convert.ToHexString(SHA256.HashData(bytes)));
if (args.Contains("--describe-runtime"))
{
    // The acceptance driver compares these observed files with Bazel producers.
    var paths = AppDomain.CurrentDomain.GetAssemblies()
        .Where(assembly => !assembly.IsDynamic && assembly.Location.Length > 0)
        .Select(assembly => assembly.Location)
        .Concat(File.ReadLines("/proc/self/maps")
            .Select(line => line.Split(' ', StringSplitOptions.RemoveEmptyEntries).Last())
            .Where(path => path.StartsWith('/')))
        .Append(Environment.ProcessPath!)
        .Distinct()
        .Order()
        .Select(path => new { path, sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))) })
        .ToArray();
    Console.WriteLine("RUNTIME=" + JsonSerializer.Serialize(new
    {
        framework = RuntimeInformation.FrameworkDescription,
        corelib = typeof(object).Assembly.Location,
        files = paths,
    }));
}
internal sealed record Message(string Text);
