using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace RulesMSBuild.ProjectCache;

// A project fingerprint is an action-cache key; the manifest and files live in
// the CAS. This uses the same HTTP cache protocol as Bazel, but keeps a separate
// key domain so Bazel cannot mistake a project snapshot for one of its actions.
public sealed class RemoteSnapshotStore(Uri endpoint) : IDisposable
{
    private readonly HttpClient client = new() { BaseAddress = endpoint, Timeout = TimeSpan.FromMinutes(2) };

    public async Task<bool> FetchAsync(string fingerprint, string destination, CancellationToken cancellationToken)
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
        Directory.CreateDirectory(destination);
        foreach (var (relative, digest) in manifest.Files)
        {
            var path = SafePath(destination, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            await File.WriteAllBytesAsync(path, await DownloadAsync(digest, cancellationToken), cancellationToken);
        }
        await File.WriteAllBytesAsync(Path.Combine(destination, "manifest.json"), manifestBytes, cancellationToken);
        return true;
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
        var existingBytes = await ReadManifestAsync(fingerprint, cancellationToken);
        if (existingBytes is not null)
        {
            var existing = JsonSerializer.Deserialize<RemoteManifest>(existingBytes)
                ?? throw new InvalidDataException("Missing existing project-cache manifest");
            if (existing.Fingerprint != fingerprint || !SameFiles(existing.Files, snapshot.Files) ||
                !SameFiles(existing.ProjectCopies, snapshot.ProjectCopies))
            {
                var changed = (existing.Files ?? []).Keys.Union((snapshot.Files ?? []).Keys, StringComparer.Ordinal)
                    .Where(path => !(existing.Files ?? []).TryGetValue(path, out var oldDigest) ||
                        !(snapshot.Files ?? []).TryGetValue(path, out var newDigest) || oldDigest != newDigest)
                    .Take(5);
                throw new InvalidDataException("Conflicting project-cache outputs for " + source +
                    " fingerprint " + fingerprint + "; changed files: " + string.Join(", ", changed));
            }
            return false;
        }
        foreach (var (relative, digest) in snapshot.Files)
        {
            var path = SafePath(source, relative.Replace('\\', '/'));
            var bytes = await File.ReadAllBytesAsync(path, cancellationToken);
            if (Digest(bytes) != digest)
            {
                throw new InvalidDataException("Project-cache file changed during upload: " + relative);
            }
            await UploadAsync("cas/" + digest, bytes, "application/octet-stream", cancellationToken);
        }
        var manifestDigest = Digest(manifest);
        await UploadAsync("cas/" + manifestDigest, manifest, "application/octet-stream", cancellationToken);
        var result = JsonSerializer.SerializeToUtf8Bytes(new
        {
            outputFiles = new[] { new { path = "manifest.json", digest = new { hash = manifestDigest, sizeBytes = manifest.Length.ToString() } } },
        });
        await UploadAsync("rules-msbuild/ac/" + ActionKey(fingerprint), result, "application/json", cancellationToken);
        return true;
    }

    private async Task<byte[]?> ReadManifestAsync(string fingerprint, CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, "rules-msbuild/ac/" + ActionKey(fingerprint));
        request.Headers.Accept.ParseAdd("application/json");
        using var response = await client.SendAsync(request, cancellationToken);
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
        var bytes = await client.GetByteArrayAsync("cas/" + digest, cancellationToken);
        if (Digest(bytes) != digest)
        {
            throw new InvalidDataException("Corrupt project-cache blob: " + digest);
        }
        return bytes;
    }

    private async Task UploadAsync(string path, byte[] bytes, string contentType, CancellationToken cancellationToken)
    {
        using var content = new ByteArrayContent(bytes);
        content.Headers.ContentType = new(contentType);
        using var response = await client.PutAsync(path, content, cancellationToken);
        response.EnsureSuccessStatusCode();
    }

    private static string SafePath(string root, string relative)
    {
        if (Path.IsPathRooted(relative) || relative.Split('/').Any(part => part is "" or "." or ".."))
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
