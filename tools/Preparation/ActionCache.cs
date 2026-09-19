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
    // Extracted NuGet trees plus project outputs exceed 2 GiB on large graphs.
    internal const long DefaultTotalLimit = 8L * 1024 * 1024 * 1024;
    private readonly long totalLimit;
    private readonly HttpClient client = new(new SocketsHttpHandler { AllowAutoRedirect = false, MaxConnectionsPerServer = 8 }) { Timeout = TimeSpan.FromSeconds(30) };
    private readonly HttpListener listener = new();
    private readonly ConcurrentBag<Task> requests = [];
    private readonly ConcurrentDictionary<string, string> staged = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, bool> lookups = new(StringComparer.Ordinal);
    private readonly string endpoint, directory, prefix;
    private readonly bool upload;
    private readonly Task serving;
    private long uploaded, downloaded, buffered, published, failures, reusedObjects, reusedBytes;
    private bool stopped;
    public string Url { get; }
    public JsonObject Statistics => new()
    {
        ["uploadEnabled"] = upload,
        ["stagingLimitBytes"] = totalLimit,
        ["lookupKeys"] = Json.Strings(lookups.Keys.Order(StringComparer.Ordinal)),
        ["hitKeys"] = Json.Strings(lookups.Where(p => p.Value).Select(p => p.Key).Order(StringComparer.Ordinal)),
        ["stagedObjects"] = staged.Count,
        ["stagedBytes"] = Interlocked.Read(ref buffered),
        ["publishedObjects"] = Interlocked.Read(ref published),
        ["uploadedBytes"] = Interlocked.Read(ref uploaded),
        ["reusedObjects"] = Interlocked.Read(ref reusedObjects),
        ["reusedBytes"] = Interlocked.Read(ref reusedBytes),
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
    public ActionCache(string endpoint, string directory, bool upload, long totalLimit = DefaultTotalLimit)
    {
        if (totalLimit <= 0) throw new ArgumentOutOfRangeException(nameof(totalLimit));
        this.totalLimit = totalLimit;
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
                            if (size > ObjectLimit || Interlocked.Add(ref buffered, count) > totalLimit) throw new InvalidDataException("Cache upload limit exceeded");
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
        try
        {
            // Probe only during accepted publication. A fresh HEAD avoids retaining
            // assumptions across invocations or cache evictions. As with ordinary
            // Bazel caches, eviction after publication can still cause a cache miss.
            PublishGroup("cas/", checkExisting: true).GetAwaiter().GetResult();
            // No action record is visible until every content operation succeeds.
            PublishGroup("ac/", checkExisting: false).GetAwaiter().GetResult();
        }
        catch { Interlocked.Increment(ref failures); throw; }
    }
    private Task PublishGroup(string group, bool checkExisting) => Parallel.ForEachAsync(
        staged.Where(pair => pair.Key.StartsWith(group, StringComparison.Ordinal)),
        new ParallelOptions { MaxDegreeOfParallelism = 8 }, async (item, cancellation) =>
        {
            var (relative, contentType) = item;
            var path = Path.Combine(directory, relative);
            var length = new FileInfo(path).Length;
            if (checkExisting)
            {
                using var probe = new HttpRequestMessage(HttpMethod.Head, endpoint + "/" + relative);
                using var existing = await client.SendAsync(probe, HttpCompletionOption.ResponseHeadersRead, cancellation);
                if (existing.StatusCode == HttpStatusCode.OK)
                {
                    if (existing.Content.Headers.ContentLength is { } size && size != length)
                        throw new InvalidDataException("Remote CAS object size mismatch");
                    Interlocked.Increment(ref reusedObjects); Interlocked.Add(ref reusedBytes, length);
                    return;
                }
                // Older HTTP caches may not implement HEAD. Upload in that case;
                // authentication, transport and server errors must fail closed.
                if (existing.StatusCode is not (HttpStatusCode.NotFound or HttpStatusCode.MethodNotAllowed or HttpStatusCode.NotImplemented))
                    throw new HttpRequestException("Remote CAS existence check failed: " + existing.StatusCode);
            }
            await using var input = File.OpenRead(path);
            using var request = new HttpRequestMessage(HttpMethod.Put, endpoint + "/" + relative) { Content = new StreamContent(input) };
            request.Content.Headers.ContentType = System.Net.Http.Headers.MediaTypeHeaderValue.Parse(contentType);
            using var response = await client.SendAsync(request, cancellation); response.EnsureSuccessStatusCode();
            Interlocked.Increment(ref published); Interlocked.Add(ref uploaded, length);
        });

    public void Dispose()
    {
        Stop(); listener.Close(); client.Dispose();
    }
}
