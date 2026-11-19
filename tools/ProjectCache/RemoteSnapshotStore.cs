using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace RulesMSBuild.ProjectCache;

// A project fingerprint is an action-cache key; the manifest and files live in
// the CAS. This uses the same HTTP cache protocol as Bazel, but keeps a separate
// key domain so Bazel cannot mistake a project snapshot for one of its actions.
// Optional disk-backed sharing across project snapshots; payload bytes are
// verified by the transport before the store publishes them.
public interface IProjectCacheContentStore
{
    Task MaterializeAsync(string digest, Func<string, CancellationToken, Task> download,
        string[] destinations, CancellationToken cancellationToken);
}

public sealed class RemoteSnapshotStore(Uri endpoint, int parallelism = 8, string? bearerToken = null, bool profile = false, IProjectCacheContentStore? contentStore = null, bool readOnly = false) : IDisposable
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
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, Lazy<Task>> uploaded = new(StringComparer.Ordinal);
    private readonly SemaphoreSlim bodies = new(Math.Clamp(parallelism, 1, 32));

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
                    var paths = group.Select(file => SafePath(staging, file.Key)).ToArray();
                    if (contentStore is not null)
                    {
                        await contentStore.MaterializeAsync(group.Key, (path, token) => DownloadToAsync(group.Key, path, token), paths, token);
                    }
                    else
                    {
                        await DownloadToAsync(group.Key, paths[0], token);
                        foreach (var path in paths.Skip(1))
                        {
                            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                            File.Copy(paths[0], path);
                        }
                    }
                });
            await File.WriteAllBytesAsync(Path.Combine(staging, "manifest.json"), manifestBytes, cancellationToken);
            // Publish only complete entries; independent consumers may finish together.
            try
            {
                Directory.Move(staging, destination);
            }
            catch (IOException) when (Directory.Exists(destination))
            {
                if (!(await File.ReadAllBytesAsync(Path.Combine(destination, "manifest.json"), cancellationToken)).SequenceEqual(manifestBytes))
                {
                    throw new InvalidDataException("Conflicting concurrent project-cache entry: " + fingerprint);
                }
            }
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
        // Consumers may rebuild a miss locally without acquiring publication rights.
        if (readOnly)
        {
            return false;
        }
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
                !System.Text.Json.Nodes.JsonNode.DeepEquals(System.Text.Json.Nodes.JsonNode.Parse(existingBytes), System.Text.Json.Nodes.JsonNode.Parse(manifest)))
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
                var upload = uploaded.GetOrAdd(digest, _ => new Lazy<Task>(() => UploadFileAsync(
                    SafePath(source, group.First().Key), digest, token), LazyThreadSafetyMode.ExecutionAndPublication));
                try
                {
                    await upload.Value;
                }
                catch
                {
                    uploaded.TryRemove(new KeyValuePair<string, Lazy<Task>>(digest, upload));
                    throw;
                }
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
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        deadline.CancelAfter(TimeSpan.FromMinutes(2));
        cancellationToken = deadline.Token;
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
        using var actionStream = await response.Content.ReadAsStreamAsync(cancellationToken);
        using var action = await JsonDocument.ParseAsync(actionStream, cancellationToken: cancellationToken);
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
        // Only small protocol manifests cross the in-memory interface.
        var temporary = Path.Combine(Path.GetTempPath(), "project-manifest-" + Guid.NewGuid().ToString("N"));
        try
        {
            await DownloadToAsync(digest, temporary, cancellationToken);
            return await File.ReadAllBytesAsync(temporary, cancellationToken);
        }
        finally
        {
            File.Delete(temporary);
        }
    }

    private async Task DownloadToAsync(string digest, string destination, CancellationToken cancellationToken)
    {
        if (!ValidDigest(digest))
        {
            throw new InvalidDataException("Invalid project-cache digest");
        }
        await bodies.WaitAsync(cancellationToken);
        try
        {
            for (var attempt = 0; ; attempt++)
            {
                try
                {
                    using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                    deadline.CancelAfter(TimeSpan.FromMinutes(2));
                    var token = deadline.Token;
                    using var response = await SendAsync(() => new HttpRequestMessage(HttpMethod.Get, "cas/" + digest), token);
                    response.EnsureSuccessStatusCode();
                    Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
                    await using var input = await response.Content.ReadAsStreamAsync(token);
                    await using var output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None, 65536, true);
                    var (actual, length) = await CopyAndHashAsync(input, output, token);
                    if (actual != digest)
                    {
                        throw new InvalidDataException("Corrupt project-cache blob: " + digest);
                    }
                    if (profile)
                    {
                        Interlocked.Add(ref downloadBytes, length);
                        Interlocked.Increment(ref downloads);
                    }
                    return;
                }
                catch (Exception error) when (attempt < 2 && !cancellationToken.IsCancellationRequested &&
                    (error is HttpRequestException http && (http.StatusCode is null or HttpStatusCode.RequestTimeout or HttpStatusCode.TooManyRequests || (int)http.StatusCode >= 500) ||
                     error is IOException && error is not InvalidDataException || error is OperationCanceledException))
                {
                    File.Delete(destination);
                    await Task.Delay(TimeSpan.FromMilliseconds(100 * (1 << attempt)), cancellationToken);
                }
            }
        }
        catch
        {
            File.Delete(destination);
            throw;
        }
        finally
        {
            bodies.Release();
        }
    }

    private async Task UploadFileAsync(string path, string digest, CancellationToken cancellationToken)
    {
        await bodies.WaitAsync(cancellationToken);
        var temporary = Path.Combine(Path.GetTempPath(), "project-upload-" + Guid.NewGuid().ToString("N"));
        try
        {
            // Capture and verify a private immutable upload before sending any
            // bytes under a claimed CAS key. A changing source must not poison CAS.
            long length;
            await using (var source = File.OpenRead(path))
            await using (var staged = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None, 65536, true))
            {
                var copied = await CopyAndHashAsync(source, staged, cancellationToken);
                if (copied.Digest != digest)
                {
                    throw new InvalidDataException("Project-cache file changed during upload: " + path);
                }
                length = copied.Length;
            }
            using var response = await SendAsync(() =>
            {
                // Each retry opens the same verified private payload afresh.
                var content = new VerifiedFileContent(temporary, digest);
                return new HttpRequestMessage(HttpMethod.Put, "cas/" + digest) { Content = content };
            }, cancellationToken);
            response.EnsureSuccessStatusCode();
            if (profile)
            {
                Interlocked.Add(ref uploadBytes, length);
                Interlocked.Increment(ref uploads);
            }
        }
        finally
        {
            try
            {
                File.Delete(temporary);
            }
            finally
            {
                bodies.Release();
            }
        }
    }

    private static async Task<(string Digest, long Length)> CopyAndHashAsync(Stream input, Stream output, CancellationToken cancellationToken)
    {
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = new byte[65536];
        long length = 0;
        int count;
        while ((count = await input.ReadAsync(buffer, cancellationToken)) != 0)
        {
            hash.AppendData(buffer, 0, count);
            await output.WriteAsync(buffer.AsMemory(0, count), cancellationToken);
            length += count;
        }
        return (Convert.ToHexStringLower(hash.GetHashAndReset()), length);
    }

    private sealed class VerifiedFileContent(string path, string digest) : HttpContent
    {
        private readonly FileStream input = File.OpenRead(path);
        protected override bool TryComputeLength(out long length)
        {
            length = input.Length;
            return true;
        }
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) =>
            SerializeToStreamAsync(stream, context, CancellationToken.None);
        protected override async Task SerializeToStreamAsync(Stream stream, TransportContext? context, CancellationToken cancellationToken)
        {
            var copied = await CopyAndHashAsync(input, stream, cancellationToken);
            if (copied.Digest != digest)
            {
                throw new InvalidDataException("Project-cache file changed during upload: " + path);
            }
        }
        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                input.Dispose();
            }

            base.Dispose(disposing);
        }
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
                var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
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
        if (!RelativePathComponents.IsSafeRelative(relative))
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
    private static bool ValidDigest(string digest) => digest.Length == 64 && digest.All(char.IsAsciiHexDigitLower);
    private static bool SameFiles(Dictionary<string, string>? left, Dictionary<string, string>? right) =>
        (left ?? []).Count == (right ?? []).Count && (left ?? []).All(file =>
            (right ?? []).TryGetValue(file.Key, out var digest) && file.Value == digest);

    public void Dispose()
    {
        client.Dispose();
        bodies.Dispose();
    }

    private sealed record RemoteManifest(string Fingerprint, Dictionary<string, string> Files, Dictionary<string, string>? ProjectCopies = null);
}

internal static class ProjectCachePolicy
{
    internal static bool ReadOnly(string? value) => value switch
    {
        null or "" or "0" => false,
        "1" => true,
        _ => throw new InvalidDataException("RULES_MSBUILD_PROJECT_CACHE_READ_ONLY must be 0 or 1")
    };
}
