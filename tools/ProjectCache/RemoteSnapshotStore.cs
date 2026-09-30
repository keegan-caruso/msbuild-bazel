using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace RulesMSBuild.ProjectCache;

// A project fingerprint is an action-cache key; the manifest and files live in
// the CAS. This uses the same HTTP cache protocol as Bazel, but keeps a separate
// key domain so Bazel cannot mistake a project snapshot for one of its actions.
public sealed class RemoteSnapshotStore(Uri endpoint, int parallelism = 8, string? bearerToken = null, bool profile = false) : IDisposable
{
    private long downloadBytes;
    private long uploadBytes;
    private long downloads;
    private long uploads;
    // Successful logical payloads, including manifests; excludes retry traffic
    // and HTTP framing. This is not a wire-level network byte measurement.
    public object? Report => profile ? new { downloadBytes, uploadBytes, downloads, uploads } : null;

    private readonly HttpClient client = CreateClient(endpoint, bearerToken);
    private readonly ParallelOptions transfers = new() { MaxDegreeOfParallelism = Math.Clamp(parallelism, 1, 32) };
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, byte> uploaded = new(StringComparer.Ordinal);

    private static HttpClient CreateClient(Uri endpoint, string? bearerToken)
    {
        var client = new HttpClient(new SocketsHttpHandler { MaxConnectionsPerServer = 8 }) { BaseAddress = endpoint, Timeout = TimeSpan.FromMinutes(2) };
        if (!string.IsNullOrEmpty(bearerToken))
        {
            client.DefaultRequestHeaders.Authorization = new("Bearer", bearerToken);
        }
        return client;
    }

    public async Task<bool> FetchAsync(string fingerprint, string destination, CancellationToken cancellationToken)
    {
        var staging = destination + ".fetch-" + Guid.NewGuid().ToString("N");
        try
        {
            var manifestBytes = await ReadManifestAsync(fingerprint, cancellationToken);
            if (manifestBytes is null)
            {
                return false;
            }
            var manifest = JsonSerializer.Deserialize<RemoteManifest>(manifestBytes)
                ?? throw new InvalidDataException("Missing project-cache manifest");
            if (manifest.Fingerprint != fingerprint || manifest.Files is null)
            {
                throw new InvalidDataException("Project-cache fingerprint mismatch");
            }
            Directory.CreateDirectory(staging);
            await Parallel.ForEachAsync(manifest.Files.GroupBy(file => file.Value),
                new ParallelOptions { MaxDegreeOfParallelism = transfers.MaxDegreeOfParallelism, CancellationToken = cancellationToken }, async (group, token) =>
                {
                    var bytes = await DownloadAsync(group.Key, token);
                    foreach (var (relative, _) in group)
                    {
                        var path = SafePath(staging, relative);
                        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                        await File.WriteAllBytesAsync(path, bytes, token);
                    }
                });
            await File.WriteAllBytesAsync(Path.Combine(staging, "manifest.json"), manifestBytes, cancellationToken);
            // Callers use unique destinations. Never expose a partially fetched entry.
            Directory.Move(staging, destination);
            return true;
        }
        catch (HttpRequestException error) when (error.StatusCode == HttpStatusCode.NotFound)
        {
            // An action-cache entry can outlive an evicted CAS blob.
            return false;
        }
        finally
        {
            if (Directory.Exists(staging))
            {
                Directory.Delete(staging, recursive: true);
            }
        }
    }

    public async Task<bool> PublishAsync(string fingerprint, string source, CancellationToken cancellationToken)
    {
        var manifest = await File.ReadAllBytesAsync(Path.Combine(source, "manifest.json"), cancellationToken);
        var snapshot = JsonSerializer.Deserialize<RemoteManifest>(manifest)
            ?? throw new InvalidDataException("Missing project-cache manifest");
        if (snapshot.Fingerprint != fingerprint || snapshot.Files is null)
        {
            throw new InvalidDataException("Project-cache fingerprint mismatch");
        }
        byte[]? existingBytes;
        try
        {
            existingBytes = await ReadManifestAsync(fingerprint, cancellationToken);
        }
        catch (HttpRequestException error) when (error.StatusCode == HttpStatusCode.NotFound)
        {
            existingBytes = null;
        }
        if (existingBytes is not null)
        {
            var existing = JsonSerializer.Deserialize<RemoteManifest>(existingBytes)
                ?? throw new InvalidDataException("Missing existing project-cache manifest");
            if (existing.Fingerprint != fingerprint || !SameFiles(existing.Files, snapshot.Files) ||
                !SameFiles(existing.ProjectCopies, snapshot.ProjectCopies) ||
                !JsonElement.DeepEquals(JsonSerializer.Deserialize<JsonElement>(existingBytes), JsonSerializer.Deserialize<JsonElement>(manifest)))
            {
                var changed = (existing.Files ?? []).Keys.Union((snapshot.Files ?? []).Keys, StringComparer.Ordinal)
                    .Where(path => !(existing.Files ?? []).TryGetValue(path, out var oldDigest) ||
                        !(snapshot.Files ?? []).TryGetValue(path, out var newDigest) || oldDigest != newDigest)
                    .Take(5);
                throw new InvalidDataException("Conflicting project-cache outputs for " + source +
                    " fingerprint " + fingerprint + "; changed files: " + string.Join(", ", changed));
            }
        }
        await Parallel.ForEachAsync(snapshot.Files.GroupBy(file => file.Value),
            new ParallelOptions { MaxDegreeOfParallelism = transfers.MaxDegreeOfParallelism, CancellationToken = cancellationToken }, async (group, token) =>
            {
                var digest = group.Key;
                if (uploaded.ContainsKey(digest))
                {
                    return;
                }
                var path = SafePath(source, group.First().Key);
                var bytes = await File.ReadAllBytesAsync(path, token);
                if (Digest(bytes) != digest)
                {
                    throw new InvalidDataException("Project-cache file changed during upload: " + path);
                }
                await UploadAsync("cas/" + digest, bytes, "application/octet-stream", token);
                uploaded.TryAdd(digest, 0);
            });
        var manifestDigest = Digest(manifest);
        await UploadAsync("cas/" + manifestDigest, manifest, "application/octet-stream", cancellationToken);
        var result = JsonSerializer.SerializeToUtf8Bytes(new
        {
            outputFiles = new[] { new { path = "manifest.json", digest = new { hash = manifestDigest, sizeBytes = manifest.Length.ToString() } } },
        });
        await UploadAsync("rules-msbuild/ac/" + ActionKey(fingerprint), result, "application/json", cancellationToken);
        return existingBytes is null;
    }

    private async Task<byte[]?> ReadManifestAsync(string fingerprint, CancellationToken cancellationToken)
    {
        using var response = await SendAsync(() =>
        {
            var request = new HttpRequestMessage(HttpMethod.Get, "rules-msbuild/ac/" + ActionKey(fingerprint));
            request.Headers.Accept.ParseAdd("application/json");
            return request;
        }, cancellationToken);
        if (response.StatusCode == HttpStatusCode.NotFound)
        {
            return null;
        }
        response.EnsureSuccessStatusCode();
        using var action = JsonDocument.Parse(await response.Content.ReadAsStreamAsync(cancellationToken));
        var outputs = action.RootElement.GetProperty("outputFiles");
        if (outputs.GetArrayLength() != 1 || outputs[0].GetProperty("path").GetString() != "manifest.json")
        {
            throw new InvalidDataException("Unexpected project-cache action result");
        }
        var manifestDigest = outputs[0].GetProperty("digest").GetProperty("hash").GetString()!;
        return await DownloadAsync(manifestDigest, cancellationToken);
    }

    private async Task<byte[]> DownloadAsync(string digest, CancellationToken cancellationToken)
    {
        if (!ValidDigest(digest))
        {
            throw new InvalidDataException("Invalid project-cache digest");
        }
        using var response = await SendAsync(() => new HttpRequestMessage(HttpMethod.Get, "cas/" + digest), cancellationToken);
        response.EnsureSuccessStatusCode();
        var bytes = await response.Content.ReadAsByteArrayAsync(cancellationToken);
        if (profile)
        {
            Interlocked.Add(ref downloadBytes, bytes.Length);
            Interlocked.Increment(ref downloads);
        }
        if (Digest(bytes) != digest)
        {
            throw new InvalidDataException("Corrupt project-cache blob: " + digest);
        }
        return bytes;
    }

    private async Task UploadAsync(string path, byte[] bytes, string contentType, CancellationToken cancellationToken)
    {
        using var response = await SendAsync(() =>
        {
            var request = new HttpRequestMessage(HttpMethod.Put, path) { Content = new ByteArrayContent(bytes) };
            request.Content.Headers.ContentType = new(contentType);
            return request;
        }, cancellationToken);
        response.EnsureSuccessStatusCode();
        if (profile)
        {
            Interlocked.Add(ref uploadBytes, bytes.Length);
            Interlocked.Increment(ref uploads);
        }
    }

    private async Task<HttpResponseMessage> SendAsync(Func<HttpRequestMessage> create, CancellationToken cancellationToken)
    {
        for (var attempt = 0; ; attempt++)
        {
            try
            {
                using var request = create();
                var response = await client.SendAsync(request, cancellationToken);
                var transient = (int)response.StatusCode is 408 or 429 or >= 500;
                if (!transient || attempt == 2)
                {
                    return response;
                }
                response.Dispose();
            }
            catch (HttpRequestException) when (attempt < 2)
            {
            }
            catch (System.Net.Sockets.SocketException) when (attempt < 2)
            {
            }
            catch (TaskCanceledException) when (attempt < 2 && !cancellationToken.IsCancellationRequested)
            {
            }
            await Task.Delay(TimeSpan.FromMilliseconds(100 * (1 << attempt)), cancellationToken);
        }
    }

    private static string SafePath(string root, string relative)
    {
        if (Path.IsPathRooted(relative) || relative.Contains('\\') || relative.Split('/').Any(part => part is "" or "." or ".."))
        {
            throw new InvalidDataException("Invalid project-cache path: " + relative);
        }
        var path = Path.GetFullPath(relative, root);
        if (!path.StartsWith(Path.TrimEndingDirectorySeparator(root) + Path.DirectorySeparatorChar, StringComparison.Ordinal))
        {
            throw new InvalidDataException("Project-cache path escaped destination");
        }
        return path;
    }

    private static string ActionKey(string fingerprint) => Digest(Encoding.UTF8.GetBytes("rules-msbuild-project-snapshot-v1\n" + fingerprint));
    private static string Digest(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));
    private static bool ValidDigest(string digest) => digest.Length == 64 && digest.All(char.IsAsciiHexDigit) && digest == digest.ToLowerInvariant();
    private static bool SameFiles(Dictionary<string, string>? left, Dictionary<string, string>? right) =>
        (left ?? []).Count == (right ?? []).Count && (left ?? []).All(file =>
            (right ?? []).TryGetValue(file.Key, out var digest) && file.Value == digest);

    public void Dispose() => client.Dispose();

    private sealed record RemoteManifest(string Fingerprint, Dictionary<string, string> Files, Dictionary<string, string>? ProjectCopies = null);
}
