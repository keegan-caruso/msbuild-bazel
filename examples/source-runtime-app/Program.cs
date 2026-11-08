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
if (args.Contains("--verify-product"))
{
    var shared = Path.GetDirectoryName(typeof(object).Assembly.Location)!;
    using var product = JsonDocument.Parse(File.ReadAllText(Path.GetFullPath(Path.Combine(shared, "../../..", "source-runtime.json"))));
    var assemblies = product.RootElement.GetProperty("managed").EnumerateObject().Select(item => item.Name).ToArray();
    foreach (var name in assemblies)
    {
        var assembly = System.Reflection.Assembly.Load(new System.Reflection.AssemblyName(Path.GetFileNameWithoutExtension(name)));
        if (Path.GetDirectoryName(assembly.Location) != shared)
        {
            throw new InvalidOperationException("Framework assembly escaped source product: " + name);
        }
    }
    if (System.Globalization.CultureInfo.GetCultureInfo("tr-TR").TextInfo.ToUpper("i") != "İ")
    {
        throw new InvalidOperationException("Source globalization failed");
    }
    var strings = Type.GetType("Microsoft.VisualBasic.Strings, Microsoft.VisualBasic.Core", throwOnError: true)!;
    if ((string)strings.GetMethod("StrReverse", [typeof(string)])!.Invoke(null, ["abc"])! != "cba")
    {
        throw new InvalidOperationException("Source Visual Basic library failed");
    }
    Console.WriteLine("PRODUCT_MEMBERS=" + assemblies.Length);
}
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
