using System.Diagnostics;
using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

internal sealed class RemoteCache : IDisposable
{
    public const string Policy = "dotnet-native-snapshot-v1";
    private const int Limit = 64 * 1024 * 1024;
    private readonly HttpClient client = new(new SocketsHttpHandler { AllowAutoRedirect = false, MaxConnectionsPerServer = 8 }) { Timeout = TimeSpan.FromSeconds(30), MaxResponseContentBufferSize = Limit };
    private readonly string endpoint;
    private long gets, heads, puts, downloaded, uploaded, failures, requestTicks;
    public JsonObject Statistics => new()
    {
        ["getRequests"] = Interlocked.Read(ref gets),
        ["headRequests"] = Interlocked.Read(ref heads),
        ["putRequests"] = Interlocked.Read(ref puts),
        ["downloadBytes"] = Interlocked.Read(ref downloaded),
        ["uploadBytes"] = Interlocked.Read(ref uploaded),
        ["failures"] = Interlocked.Read(ref failures),
        ["requestSeconds"] = (double)Interlocked.Read(ref requestTicks) / TimeSpan.TicksPerSecond
    };
    private HttpResponseMessage Send(HttpRequestMessage request)
    {
        using (request)
        {
            if (request.Method == HttpMethod.Get) Interlocked.Increment(ref gets);
            if (request.Method == HttpMethod.Head) Interlocked.Increment(ref heads);
            if (request.Method == HttpMethod.Put) { Interlocked.Increment(ref puts); Interlocked.Add(ref uploaded, request.Content?.Headers.ContentLength ?? 0); }
            var timer = Stopwatch.StartNew();
            try
            {
                var response = client.Send(request);
                if ((int)response.StatusCode >= 500) Interlocked.Increment(ref failures);
                return response;
            }
            catch { Interlocked.Increment(ref failures); throw; }
            finally { Interlocked.Add(ref requestTicks, timer.Elapsed.Ticks); }
        }
    }
    public RemoteCache(string endpoint)
    {
        var uri = new Uri(endpoint);
        if (uri.Scheme is not ("http" or "https") || uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0) throw new InvalidDataException("Invalid cache endpoint");
        this.endpoint = endpoint.TrimEnd('/');
    }
    public static string Digest(string value) => value.Length == 64 && value.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f') ? value : throw new InvalidDataException("Invalid CAS digest");
    public byte[] Fetch(string hash)
    {
        using var response = Send(new HttpRequestMessage(HttpMethod.Get, endpoint + "/cas/" + Digest(hash)));
        response.EnsureSuccessStatusCode();
        var data = response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult();
        Interlocked.Add(ref downloaded, data.LongLength);
        if (data.Length > Limit || Json.Sha(data) != hash) throw new InvalidDataException("CAS digest mismatch");
        return data;
    }
    public string Upload(byte[] data)
    {
        if (data.Length > Limit) throw new InvalidDataException("CAS object exceeds limit");
        var hash = Json.Sha(data); var url = endpoint + "/cas/" + hash;
        using (var head = Send(new HttpRequestMessage(HttpMethod.Head, url)))
        {
            if (head.IsSuccessStatusCode && head.Content.Headers.ContentLength == data.Length) return hash;
            if (!head.IsSuccessStatusCode && head.StatusCode is not (HttpStatusCode.NotFound or HttpStatusCode.MethodNotAllowed or HttpStatusCode.NotImplemented)) head.EnsureSuccessStatusCode();
        }
        using var response = Send(new HttpRequestMessage(HttpMethod.Put, url) { Content = new ByteArrayContent(data) }); response.EnsureSuccessStatusCode(); return hash;
    }
    internal static byte[] Pack(Dictionary<string, byte[]> files)
    {
        using var memory = new MemoryStream();
        using (var archive = new ZipArchive(memory, ZipArchiveMode.Create, true))
            foreach (var (name, data) in files.OrderBy(p => p.Key, StringComparer.Ordinal))
            {
                Host.Safe(name); var entry = archive.CreateEntry(name, CompressionLevel.Fastest); entry.LastWriteTime = new DateTimeOffset(1980, 1, 1, 0, 0, 0, TimeSpan.Zero);
                using var stream = entry.Open(); stream.Write(data);
            }
        if (memory.Length > Limit) throw new InvalidDataException("CAS archive exceeds limit");
        return memory.ToArray();
    }
    internal static Dictionary<string, byte[]> Unpack(byte[] bytes, long maximum = Limit)
    {
        using var archive = new ZipArchive(new MemoryStream(bytes)); var files = new Dictionary<string, byte[]>(StringComparer.Ordinal); long total = 0;
        foreach (var entry in archive.Entries)
        {
            var name = Host.Safe(entry.FullName); total += entry.Length;
            if (files.ContainsKey(name) || total > maximum || files.Count >= 100000 || ((entry.ExternalAttributes >> 16) & 0xf000) == 0xa000) throw new InvalidDataException("Invalid archive member");
            using var input = entry.Open(); using var data = new MemoryStream(); input.CopyTo(data);
            if (data.Length != entry.Length) throw new InvalidDataException("Archive size mismatch");
            files[name] = data.ToArray();
        }
        return files;
    }
    internal static JsonNode ValidateBundle(Dictionary<string, byte[]> files) =>
        BundleIntegrity.Validate(files.Keys, name => files[name]);
    public JsonNode Snapshot(string hash, JsonNode? worker = null)
    {
        var value = JsonNode.Parse(Fetch(hash))!;
        if (value["policy"]?.GetValue<string>() != Policy || value["projects"] is not JsonArray projects || projects.Count > 100000) throw new InvalidDataException("Unsupported snapshot");
        if (value["preparation"] is { } preparation) Digest(preparation.GetValue<string>());
        if (worker is not null) WorkerIdentity.RequireCompatible(value["worker"], worker);
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var record in projects)
        {
            foreach (var field in new[] { "key", "inputs", "toolchain", "blob" }) Digest(record!.String(field));
            Host.Safe(record!.String("project")); if (!seen.Add(record.String("key"))) throw new InvalidDataException("Duplicate project catalog key");
        }
        return value;
    }
    public void Seeds(JsonNode catalog, JsonNode? manifest, string destination)
    {
        Directory.CreateDirectory(destination);
        Parallel.ForEach(catalog.AsArray().Select(n => n!), new ParallelOptions { MaxDegreeOfParallelism = 8 }, record =>
        {
            if (manifest is not null && (record.String("toolchain") != manifest.String("toolchain") || manifest["projects"]?[record.String("project")]?["identity"]?.GetValue<string>() != record.String("inputs"))) return;
            try
            {
                var files = Unpack(Fetch(record.String("blob"))); var result = ValidateBundle(files);
                if (new[] { "key", "project", "inputs", "toolchain" }.Any(k => result.String(k) != record.String(k))) throw new InvalidDataException("Catalog/result mismatch");
                foreach (var (path, data) in files) { var target = Path.Combine(destination, result.String("key"), path); Directory.CreateDirectory(Path.GetDirectoryName(target)!); File.WriteAllBytes(target, data); }
            }
            catch (Exception error) when (error is IOException or HttpRequestException or InvalidDataException or System.Text.Json.JsonException or KeyNotFoundException or TaskCanceledException) { /* A rejected seed is a project cache miss. */ }
        });
    }
    private static Dictionary<string, byte[]> ReadFiles(string root)
    {
        FileTree.Snapshot(root); return FileTree.Files(root).ToDictionary(p => Path.GetRelativePath(root, p), File.ReadAllBytes, StringComparer.Ordinal);
    }
    public string Publish(string cache, string? plan, JsonNode? receipt, JsonNode? worker = null)
    {
        var projects = Directory.GetDirectories(cache).Order(StringComparer.Ordinal).AsParallel().AsOrdered().WithDegreeOfParallelism(8).Select(folder =>
        {
            var files = ReadFiles(folder); var result = ValidateBundle(files); var blob = Upload(Pack(files));
            return new JsonObject { ["key"] = result["key"]!.DeepClone(), ["project"] = result["project"]!.DeepClone(), ["inputs"] = result["inputs"]!.DeepClone(), ["toolchain"] = result["toolchain"]!.DeepClone(), ["blob"] = blob };
        }).ToArray();
        var preparation = plan is not null && receipt is not null ? PublishPreparation(plan, receipt) : null;
        return Upload(Encoding.UTF8.GetBytes(Json.Canonical(new JsonObject { ["policy"] = Policy, ["worker"] = worker?.DeepClone(), ["projects"] = new JsonArray(projects.Cast<JsonNode?>().ToArray()), ["preparation"] = preparation })));
    }
    private string PublishPreparation(string plan, JsonNode receipt)
    {
        var snapshot = FileTree.Snapshot(plan);
        if (Json.Digest(snapshot) != receipt.String("payload")) throw new InvalidDataException("Preparation changed before upload");
        var groups = snapshot.Where(p => p.Value!.String("kind") == "file").GroupBy(p => p.Key.StartsWith("src/.nuget/packages/", StringComparison.Ordinal) ? string.Join('/', p.Key.Split('/').Take(5)) : Path.GetDirectoryName(p.Key) ?? "").ToArray();
        var components = groups.AsParallel().AsOrdered().WithDegreeOfParallelism(8).Select(group =>
        {
            var files = group.ToDictionary(p => p.Key, p => File.ReadAllBytes(Path.Combine(plan, p.Key)), StringComparer.Ordinal);
            foreach (var (path, bytes) in files) if (Json.Sha(bytes) != snapshot[path]!.String("sha256")) throw new InvalidDataException("Component changed before upload");
            return (JsonNode)new JsonObject { ["blob"] = Upload(Pack(files)), ["paths"] = Json.Strings(files.Keys.Order(StringComparer.Ordinal)) };
        }).ToArray();
        FileTree.Verify(plan, snapshot);
        return Upload(Pack(new Dictionary<string, byte[]> { ["preparation.json"] = Encoding.UTF8.GetBytes(Json.Canonical(new JsonObject { ["policy"] = Policy, ["receipt"] = receipt.DeepClone(), ["files"] = snapshot, ["components"] = new JsonArray(components.Cast<JsonNode?>().ToArray()) })) }));
    }
    public JsonNode Preparation(string hash, string plan, string[] caches)
    {
        var descriptor = Unpack(Fetch(hash));
        if (descriptor.Count != 1 || !descriptor.ContainsKey("preparation.json")) throw new InvalidDataException("Invalid preparation descriptor");
        var metadata = JsonNode.Parse(descriptor["preparation.json"])!;
        if (metadata["policy"]?.GetValue<string>() != Policy) throw new InvalidDataException("Preparation policy mismatch");
        var files = metadata["files"]!.AsObject(); var occupied = new HashSet<string>(StringComparer.Ordinal); long total = 0;
        if (files.Count > 100000 || metadata.Array("components").Count > 10000) throw new InvalidDataException("Excessive preparation inventory");
        foreach (var (name, record) in files)
        {
            if (name != ".") Host.Safe(name);
            var mode = record!["mode"]!.GetValue<int>(); if (mode < 0 || mode > 511) throw new InvalidDataException("Invalid preparation mode");
            if (record.String("kind") == "file") { Digest(record.String("sha256")); var size = record["size"]!.GetValue<long>(); if (size < 0) throw new InvalidDataException("Invalid file size"); total += size; }
            else if (record.String("kind") != "directory") throw new InvalidDataException("Invalid preparation member");
        }
        if (total > 512L * 1024 * 1024 || files["."]?.String("kind") != "directory") throw new InvalidDataException("Invalid preparation size/root");
        foreach (var component in metadata.Array("components"))
        {
            Digest(component!.String("blob"));
            foreach (var path in component.Array("paths").Select(n => n!.GetValue<string>())) if (files[path]?.String("kind") != "file" || !occupied.Add(path)) throw new InvalidDataException("Overlapping component paths");
        }
        if (!occupied.SetEquals(files.Where(p => p.Value!.String("kind") == "file").Select(p => p.Key))) throw new InvalidDataException("Incomplete component inventory");
        foreach (var name in files.Select(p => p.Key))
        {
            var parent = Path.GetDirectoryName(name);
            while (!string.IsNullOrEmpty(parent)) { if (files[parent]?.String("kind") != "directory") throw new InvalidDataException("Missing or non-directory parent"); parent = Path.GetDirectoryName(parent); }
        }
        if (Path.Exists(plan)) throw new InvalidDataException("Preparation destination exists"); Directory.CreateDirectory(plan);
        foreach (var (name, record) in files.Where(p => p.Value!.String("kind") == "directory")) Directory.CreateDirectory(Path.Combine(plan, name));
        Parallel.ForEach(metadata.Array("components").Select(n => n!), new ParallelOptions { MaxDegreeOfParallelism = 8 }, component =>
        {
            var paths = component.Array("paths").Select(n => n!.GetValue<string>()).ToArray();
            Dictionary<string, byte[]>? data = null;
            if (paths.All(p => p.StartsWith("src/.nuget/packages/", StringComparison.Ordinal)))
                foreach (var cache in caches)
                {
                    try
                    {
                        var candidate = new Dictionary<string, byte[]>(StringComparer.Ordinal);
                        foreach (var path in paths) candidate[path] = LocalPackage(cache, path[20..], files[path]!);
                        data = candidate; break;
                    }
                    catch (Exception error) when (error is IOException or InvalidDataException or KeyNotFoundException) { }
                }
            data ??= Unpack(Fetch(component.String("blob")), paths.Sum(p => files[p]!["size"]!.GetValue<long>()));
            if (!data.Keys.ToHashSet().SetEquals(paths)) throw new InvalidDataException("Component membership differs");
            foreach (var (name, bytes) in data)
            {
                if (bytes.LongLength != files[name]!["size"]!.GetValue<long>() || Json.Sha(bytes) != files[name]!.String("sha256")) throw new InvalidDataException("Component contents differ");
                var path = Path.Combine(plan, name); File.WriteAllBytes(path, bytes); FileTree.SetMode(path, (UnixFileMode)files[name]!["mode"]!.GetValue<int>());
            }
        });
        foreach (var (name, record) in files.Where(p => p.Value!.String("kind") == "directory").OrderByDescending(p => p.Key.Length)) FileTree.SetMode(Path.Combine(plan, name), (UnixFileMode)record!["mode"]!.GetValue<int>());
        var receipt = metadata["receipt"]!;
        if (Json.Digest(FileTree.Snapshot(plan)) != receipt.String("payload")) throw new InvalidDataException("Preparation payload mismatch"); return receipt.DeepClone();
    }
    private static byte[] LocalPackage(string cache, string relative, JsonNode expected)
    {
        Host.Safe(relative); var path = Path.Combine(cache, relative); if (Host.Real(path) != path) throw new InvalidDataException("Linked package cache");
        byte[] data;
        if (File.Exists(path) && !path.EndsWith(".nupkg.sha512", StringComparison.Ordinal)) data = File.ReadAllBytes(path);
        else
        {
            var parts = relative.Split('/'); var folder = Path.Combine(cache, parts[0], parts[1]); var archive = Path.Combine(folder, parts[0] + "." + parts[1] + ".nupkg");
            if (Host.Real(archive) != archive) throw new InvalidDataException("Linked package archive");
            var bytes = File.ReadAllBytes(archive);
            if (path.EndsWith(".nupkg.sha512", StringComparison.Ordinal)) data = Encoding.ASCII.GetBytes(Convert.ToBase64String(SHA512.HashData(bytes)));
            else
            {
                using var zip = new ZipArchive(new MemoryStream(bytes)); var member = zip.GetEntry(string.Join('/', parts.Skip(2))) ?? throw new InvalidDataException("Missing local package member");
                if (member.Length != expected["size"]!.GetValue<long>()) throw new InvalidDataException("Package member size mismatch");
                using var input = member.Open(); using var stream = new MemoryStream(); input.CopyTo(stream); data = stream.ToArray();
            }
        }
        if (data.LongLength != expected["size"]!.GetValue<long>() || Json.Sha(data) != expected.String("sha256")) throw new InvalidDataException("Local package differs"); return data;
    }
    public void Dispose() => client.Dispose();
}
