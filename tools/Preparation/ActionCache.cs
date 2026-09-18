using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

// Bazel may upload a successful build before tests or the controller lease fail.
// This per-invocation HTTP gate stages writes and publishes only after acceptance.
internal sealed class ActionCache : IDisposable
{
    private const long ObjectLimit = 256L * 1024 * 1024;
    private const long TotalLimit = 2L * 1024 * 1024 * 1024;
    private readonly HttpClient client = new(new SocketsHttpHandler { AllowAutoRedirect = false, MaxConnectionsPerServer = 8 }) { Timeout = TimeSpan.FromSeconds(30) };
    private readonly HttpListener listener = new();
    private readonly ConcurrentBag<Task> requests = [];
    private readonly ConcurrentDictionary<string, string> staged = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, bool> lookups = new(StringComparer.Ordinal);
    private readonly string endpoint, directory, prefix;
    private readonly bool upload;
    private readonly Task serving;
    private long uploaded, downloaded, buffered, published, failures;
    private bool stopped;
    public string Url { get; }
    public JsonObject Statistics => new()
    {
        ["uploadEnabled"] = upload,
        ["lookupKeys"] = Json.Strings(lookups.Keys.Order(StringComparer.Ordinal)),
        ["hitKeys"] = Json.Strings(lookups.Where(p => p.Value).Select(p => p.Key).Order(StringComparer.Ordinal)),
        ["stagedObjects"] = staged.Count,
        ["stagedBytes"] = Interlocked.Read(ref buffered),
        ["publishedObjects"] = Interlocked.Read(ref published),
        ["uploadedBytes"] = Interlocked.Read(ref uploaded),
        ["downloadedBytes"] = Interlocked.Read(ref downloaded),
        ["failures"] = Interlocked.Read(ref failures)
    };
    internal static string Endpoint(string value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https") ||
            uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0)
            throw new InvalidDataException("Action cache requires an HTTP(S) endpoint without credentials, query or fragment");
        return uri.AbsoluteUri.TrimEnd('/');
    }
    public ActionCache(string endpoint, string directory, bool upload)
    {
        this.endpoint = Endpoint(endpoint); this.directory = directory; this.upload = upload;
        Directory.CreateDirectory(directory);
        prefix = "/" + Guid.NewGuid().ToString("N") + "/";
        for (var attempt = 0; ; attempt++)
        {
            using var socket = new TcpListener(IPAddress.Loopback, 0); socket.Start();
            var port = ((IPEndPoint)socket.LocalEndpoint).Port; socket.Stop();
            Url = "http://127.0.0.1:" + port + prefix;
            listener.Prefixes.Clear(); listener.Prefixes.Add(Url);
            try { listener.Start(); break; }
            catch (HttpListenerException) when (attempt < 4) { }
        }
        serving = Serve();
    }
    private async Task Serve()
    {
        try
        {
            while (listener.IsListening)
            {
                var context = await listener.GetContextAsync();
                requests.Add(Handle(context));
            }
        }
        catch (Exception error) when (error is HttpListenerException or ObjectDisposedException) { }
    }
    private async Task Handle(HttpListenerContext context)
    {
        var response = context.Response;
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(60));
        try
        {
            var request = context.Request;
            var path = request.Url!.AbsolutePath;
            if (!path.StartsWith(prefix, StringComparison.Ordinal) || request.Url.Query.Length != 0) throw new InvalidDataException("Invalid cache path");
            var relative = path[prefix.Length..]; var parts = relative.Split('/');
            if (parts.Length != 2 || parts[0] is not ("ac" or "cas")) throw new InvalidDataException("Invalid cache path");
            RemoteCache.Digest(parts[1]);
            if (request.HttpMethod == "PUT")
            {
                if (!upload) { response.StatusCode = 403; return; }
                if (request.ContentLength64 > ObjectLimit || !string.IsNullOrEmpty(request.Headers["Content-Encoding"])) throw new InvalidDataException("Unsupported cache upload");
                var folder = Path.Combine(directory, parts[0]); Directory.CreateDirectory(folder);
                var temporary = Path.Combine(folder, Guid.NewGuid().ToString("N") + ".pending");
                try
                {
                    await using (var file = File.Create(temporary))
                    {
                        var buffer = new byte[65536]; long size = 0; int count;
                        while ((count = await request.InputStream.ReadAsync(buffer, timeout.Token)) != 0)
                        {
                            size += count;
                            if (size > ObjectLimit || Interlocked.Add(ref buffered, count) > TotalLimit) throw new InvalidDataException("Cache upload limit exceeded");
                            await file.WriteAsync(buffer.AsMemory(0, count), timeout.Token);
                        }
                    }
                    if (parts[0] == "cas" && FileTree.HashRegular(temporary).Digest != parts[1]) throw new InvalidDataException("CAS upload digest mismatch");
                    File.Move(temporary, Path.Combine(directory, relative), true);
                    staged[relative] = request.ContentType ?? "application/octet-stream";
                    response.StatusCode = 200;
                }
                finally { File.Delete(temporary); }
            }
            else if (request.HttpMethod is "GET" or "HEAD")
            {
                using var message = new HttpRequestMessage(new HttpMethod(request.HttpMethod), endpoint + "/" + relative);
                using var result = await client.SendAsync(message, HttpCompletionOption.ResponseHeadersRead, timeout.Token);
                response.StatusCode = (int)result.StatusCode;
                if (parts[0] == "ac" && request.HttpMethod == "GET") lookups[parts[1]] = result.IsSuccessStatusCode;
                if (result.Content.Headers.ContentLength is { } length) response.ContentLength64 = length;
                else if (request.HttpMethod != "HEAD") response.SendChunked = true;
                if (result.Content.Headers.ContentType is { } contentType) response.ContentType = contentType.ToString();
                if (request.HttpMethod != "HEAD")
                {
                    await using var stream = await result.Content.ReadAsStreamAsync(timeout.Token);
                    var buffer = new byte[65536]; int count;
                    while ((count = await stream.ReadAsync(buffer, timeout.Token)) != 0)
                    {
                        await response.OutputStream.WriteAsync(buffer.AsMemory(0, count), timeout.Token);
                        Interlocked.Add(ref downloaded, count);
                    }
                }
            }
            else response.StatusCode = 405;
        }
        catch (Exception error) when (error is IOException or HttpRequestException or InvalidDataException or OperationCanceledException or HttpListenerException or ObjectDisposedException)
        {
            Interlocked.Increment(ref failures);
            try { response.StatusCode = error is InvalidDataException ? 400 : 502; } catch (InvalidOperationException) { }
        }
        finally { response.Close(); }
    }
    public void Stop()
    {
        if (stopped) return;
        stopped = true; listener.Stop(); serving.GetAwaiter().GetResult();
        Task.WhenAll(requests).GetAwaiter().GetResult();
    }
    public void Publish()
    {
        Stop();
        if (Interlocked.Read(ref failures) != 0) throw new InvalidDataException("Action cache transport failed; staged publication discarded");
        // All referenced content is committed before an action result becomes visible.
        foreach (var (relative, contentType) in staged.OrderBy(p => p.Key.StartsWith("ac/", StringComparison.Ordinal)).ThenBy(p => p.Key, StringComparer.Ordinal))
        {
            using var input = File.OpenRead(Path.Combine(directory, relative));
            using var request = new HttpRequestMessage(HttpMethod.Put, endpoint + "/" + relative) { Content = new StreamContent(input) };
            request.Content.Headers.ContentType = System.Net.Http.Headers.MediaTypeHeaderValue.Parse(contentType);
            using var response = client.Send(request); response.EnsureSuccessStatusCode();
            Interlocked.Increment(ref published); Interlocked.Add(ref uploaded, input.Length);
        }
    }
    public void Dispose()
    {
        Stop(); listener.Close(); client.Dispose();
    }
}
