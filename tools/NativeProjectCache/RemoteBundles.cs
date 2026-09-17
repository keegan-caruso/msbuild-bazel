using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using ActionRunner;

// Owned loopback probe only. This is a distinct index protocol, not Bazel ActionResult.
internal sealed class RemoteBundles : IDisposable
{
    private readonly HttpClient client = new(new SocketsHttpHandler { UseProxy = false, AllowAutoRedirect = false, MaxConnectionsPerServer = 16 }) { Timeout = TimeSpan.FromSeconds(5), MaxResponseContentBufferSize = 64 * 1024 * 1024 };
    private readonly string endpoint;
    private readonly Action<string> diagnostic;
    private bool unavailable;
    internal RemoteBundles(string endpoint, Action<string> diagnostic)
    {
        var uri = new Uri(endpoint);
        if (uri.Scheme != "http" || uri.Host != "127.0.0.1" || uri.AbsolutePath != "/native" || uri.Query.Length != 0 || uri.UserInfo.Length != 0)
            throw new InvalidDataException("remote prototype requires owned loopback endpoint");
        this.endpoint = endpoint;
        this.diagnostic = diagnostic;
    }
    private static string Digest(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));
    internal async Task<bool> Fetch(string key, string destination, CancellationToken token)
    {
        if (unavailable) return false;
        var temporary = destination + ".download";
        try
        {
            using var index = await client.GetAsync(endpoint + "/index/" + key, token);
            if (index.StatusCode == HttpStatusCode.NotFound) return false;
            index.EnsureSuccessStatusCode();
            var digest = await index.Content.ReadAsStringAsync(token);
            if (digest.Length != 64 || digest.Any(c => !"0123456789abcdef".Contains(c))) throw new InvalidDataException("invalid remote index");
            using var blob = await client.GetAsync(endpoint + "/cas/" + digest, token);
            if (blob.StatusCode == HttpStatusCode.NotFound) { diagnostic("missing-blob"); return false; }
            blob.EnsureSuccessStatusCode();
            var bytes = await blob.Content.ReadAsByteArrayAsync(token);
            if (Digest(bytes) != digest) throw new InvalidDataException("remote blob hash mismatch");
            Directory.CreateDirectory(temporary);
            using var archive = new ZipArchive(new MemoryStream(bytes), ZipArchiveMode.Read);
            long total = 0;
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var entry in archive.Entries)
            {
                total += entry.Length;
                if (total > 64 * 1024 * 1024 || !Files.ValidRelativePath(entry.FullName) || !names.Add(entry.FullName) ||
                    entry.FullName.Contains('\\') || (entry.ExternalAttributes >> 16 & 0xf000) == 0xa000)
                    throw new InvalidDataException("invalid remote archive member");
                var path = Path.Combine(temporary, entry.FullName);
                Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                entry.ExtractToFile(path);
            }
            CompileBoundary.Validate(temporary);
            Directory.Move(temporary, destination);
            diagnostic("download");
            return true;
        }
        catch (Exception error) when (error is HttpRequestException or IOException or InvalidDataException or System.Text.Json.JsonException || error is TaskCanceledException && !token.IsCancellationRequested)
        {
            if (error is HttpRequestException or TaskCanceledException) unavailable = true;
            diagnostic("fallback: " + error.GetType().Name + ": " + error.Message);
            return false;
        }
        finally { if (Directory.Exists(temporary)) Directory.Delete(temporary, true); }
    }
    internal async Task Publish(string key, string bundle, CancellationToken token)
    {
        if (unavailable) return;
        try
        {
            using var memory = new MemoryStream();
            using (var archive = new ZipArchive(memory, ZipArchiveMode.Create, true))
                foreach (var file in Directory.EnumerateFiles(bundle, "*", SearchOption.AllDirectories).Order(StringComparer.Ordinal))
                {
                    var entry = archive.CreateEntry(Path.GetRelativePath(bundle, file), CompressionLevel.Fastest);
                    entry.LastWriteTime = new DateTimeOffset(1980, 1, 1, 0, 0, 0, TimeSpan.Zero);
                    using var output = entry.Open();
                    using var input = File.OpenRead(file);
                    input.CopyTo(output);
                }
            var bytes = memory.ToArray();
            using var blob = await client.PutAsync(endpoint + "/cas/" + Digest(bytes), new ByteArrayContent(bytes), token);
            blob.EnsureSuccessStatusCode();
            using var index = await client.PutAsync(endpoint + "/index/" + key, new ByteArrayContent(Encoding.UTF8.GetBytes(Digest(bytes))), token);
            index.EnsureSuccessStatusCode();
            diagnostic("upload");
        }
        catch (Exception error) when (error is HttpRequestException || error is TaskCanceledException && !token.IsCancellationRequested)
        {
            unavailable = true;
            diagnostic("upload-fallback: " + error.GetType().Name);
        }
    }
    public void Dispose() => client.Dispose();
}
