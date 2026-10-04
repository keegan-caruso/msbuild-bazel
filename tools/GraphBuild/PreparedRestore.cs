using System.Text.Json;

namespace RulesMSBuild.GraphBuild;

// Preparation is opt-in: its authored input/output lists are a complete Restore
// contract, independent of the compiler's source inputs. Paths stay explicit.
internal sealed record PreparedFile(string Digest, int Mode);
internal sealed record RestoreManifest(int Version, string Key, string SdkDigest, Dictionary<string, PreparedFile> Files);
internal sealed record RestoredInputs(GraphContract Contract, string SdkDigest, Dictionary<string, string> Digests, bool ReadOnlyPackages = false);

internal static class PreparedRestore
{
    internal static void Create(GraphContract contract, string root, string sdk, string destination)
    {
        var files = new ContractFiles(root, sdk);
        Validate(contract, files);
        var sdkDigest = ContractFiles.TreeDigest(sdk);
        var key = Key(contract, files, sdkDigest);
        if (contract.Restore!.Outputs.Any(path => File.Exists(files.Resolve(path))) ||
            (Directory.Exists(Path.Combine(root, ".nuget")) && Directory.EnumerateFileSystemEntries(Path.Combine(root, ".nuget")).Any()))
        {
            throw new InvalidDataException("Restore preparation requires absent outputs and an empty package directory");
        }
        var original = Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories)
            .Select(path => Path.GetRelativePath(root, path)).ToDictionary(path => path, path => ContractFiles.InputDigest(files.Resolve(path)), StringComparer.Ordinal);
        Restore.Run(contract, root, sdk);
        var generated = contract.Restore!.Outputs.Append(".package-source/NuGet.Config").Concat(Directory.Exists(Path.Combine(root, ".nuget"))
            ? Directory.EnumerateFiles(Path.Combine(root, ".nuget"), "*", SearchOption.AllDirectories).Select(path => Path.GetRelativePath(root, path)) : [])
            .Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
        var allowed = generated.ToHashSet(StringComparer.Ordinal);
        foreach (var path in Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories).Select(path => Path.GetRelativePath(root, path)))
        {
            if (!original.ContainsKey(path) && !allowed.Contains(path) && path != ".package-source/NuGet.Config")
            {
                throw new InvalidDataException("Undeclared Restore output: " + path);
            }
        }
        foreach (var (path, digest) in original)
        {
            if (path != ".package-source/NuGet.Config" && ContractFiles.InputDigest(files.Resolve(path)) != digest)
            {
                throw new InvalidDataException("Restore modified a workspace input: " + path);
            }
        }
        if (Key(contract, files, sdkDigest) != key)
        {
            throw new InvalidDataException("Restore modified its declared inputs");
        }
        if (Directory.Exists(destination))
        {
            throw new InvalidDataException("Prepared Restore output must be absent: " + destination);
        }
        var staging = destination + ".staging-" + Guid.NewGuid().ToString("N");
        try
        {
            Directory.CreateDirectory(staging);
            var records = new Dictionary<string, PreparedFile>(StringComparer.Ordinal);
            foreach (var relative in generated)
            {
                var source = files.Resolve(relative);
                if (!File.Exists(source))
                {
                    throw new InvalidDataException("Missing declared Restore output: " + relative);
                }
                var target = Path.Combine(staging, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                File.Copy(source, target);
                records.Add(relative, new(ContractFiles.Digest(target), OperatingSystem.IsWindows() ? 0 : (int)File.GetUnixFileMode(target)));
            }
            File.WriteAllText(Path.Combine(staging, "manifest.json"), JsonSerializer.Serialize(new RestoreManifest(1, key, sdkDigest, records)));
            Directory.Move(staging, destination);
        }
        finally
        {
            if (Directory.Exists(staging))
            {
                Directory.Delete(staging, recursive: true);
            }
        }
    }

    internal static RestoredInputs Apply(GraphContract contract, string root, string sdk, string source, bool readOnlyPackages = false)
    {
        var files = new ContractFiles(root, sdk);
        using (GraphProfile.Measure("preparedContract"))
        {
            Validate(contract, files);
        }
        RestoreManifest manifest;
        using (GraphProfile.Measure("preparedManifest"))
        {
            manifest = JsonSerializer.Deserialize<RestoreManifest>(File.ReadAllText(Path.Combine(source, "manifest.json")))
                ?? throw new InvalidDataException("Missing prepared Restore manifest");
        }
        string sdkDigest;
        using (GraphProfile.Measure("preparedSdk"))
        {
            sdkDigest = ContractFiles.TreeDigest(sdk);
        }
        string key;
        using (GraphProfile.Measure("preparedKey"))
        {
            key = Key(contract, files, sdkDigest);
        }
        if (manifest.Version != 1 || manifest.SdkDigest != sdkDigest || manifest.Key != key)
        {
            throw new InvalidDataException("Prepared Restore inputs changed; rebuild preparation");
        }
        if (contract.Restore!.Outputs.Any(path => !manifest.Files.ContainsKey(path)))
        {
            throw new InvalidDataException("Prepared Restore is missing a declared output");
        }
        if (readOnlyPackages)
        {
            ReadOnlyPackageTree.RequireReadOnly(Path.Combine(source, ".nuget"));
            ReadOnlyPackageTree.RequireReadOnly(Path.Combine(root, ".nuget"));
        }
        var prepared = new ContractFiles(source, sdk);
        var allowed = contract.Restore.Outputs.Append(".package-source/NuGet.Config").ToHashSet(StringComparer.Ordinal);
        var digests = new Dictionary<string, string>(StringComparer.Ordinal);
        Dictionary<string, string> sources;
        Dictionary<string, string> destinations;
        using (GraphProfile.Measure("preparedPaths"))
        {
            sources = prepared.ResolveInputs(manifest.Files.Keys);
            destinations = files.ResolveInputs(manifest.Files.Keys);
        }
        // Hash every byte in this child. Parallelism is bounded and the complete
        // verification barrier precedes any Restore writes or project evaluation.
        using (GraphProfile.Measure("preparedVerification"))
        {
            try
            {
                Parallel.ForEach(manifest.Files, new ParallelOptions { MaxDegreeOfParallelism = Math.Min(Environment.ProcessorCount, 4) }, pair =>
                {
                    var (relative, record) = pair;
                    using (GraphProfile.Measure("preparedPayload", GraphProfile.Enabled ? new FileInfo(sources[relative]).Length : 0))
                    {
                        if ((!allowed.Contains(relative) && !relative.StartsWith(".nuget/", StringComparison.Ordinal)) ||
                            ContractFiles.Digest(sources[relative]) != record.Digest || (record.Mode & ~0xFFF) != 0)
                        {
                            throw new InvalidDataException("Invalid prepared Restore file: " + relative);
                        }
                    }
                    var destination = destinations[relative];
                    using var identity = GraphProfile.Measure("preparedIdentity");
                    if (readOnlyPackages && ReadOnlyPackageTree.Contains(relative))
                    {
                        ReadOnlyPackageTree.RequireSameFile(sources[relative], destination, record.Mode);
                    }
                    else if (File.Exists(destination) && ContractFiles.InputDigest(destination) != InputDigest(record))
                    {
                        throw new InvalidDataException("Prepared Restore conflicts with existing workspace file: " + relative);
                    }
                });
            }
            catch (AggregateException error)
            {
                System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(error.Flatten().InnerExceptions[0]).Throw();
            }
        }
        foreach (var (relative, record) in manifest.Files)
        {
            using var copy = GraphProfile.Measure("preparedCopy");
            var destination = destinations[relative];
            if (!File.Exists(destination))
            {
                Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
                File.Copy(sources[relative], destination);
                if (!OperatingSystem.IsWindows())
                {
                    File.SetUnixFileMode(destination, (UnixFileMode)record.Mode);
                }
            }
            digests.Add(relative, InputDigest(record));
        }
        return new(contract with
        {
            SharedInputs = contract.SharedInputs.Concat(manifest.Files.Keys.Where(path => path.StartsWith(".nuget/", StringComparison.Ordinal))).Distinct().ToArray()
        }, sdkDigest, digests, readOnlyPackages);
    }

    // Bazel normalizes tree-artifact permissions. Validate payload bytes, then
    // restore the declared mode in the owned workspace before using its digest.
    private static string InputDigest(PreparedFile file) => ContractFiles.Hash([file.Digest, OperatingSystem.IsWindows() ? "" :
        (file.Mode & 0x49).ToString(System.Globalization.CultureInfo.InvariantCulture)]);

    private static void Validate(GraphContract contract, ContractFiles files)
    {
        if (contract.Restore is null || contract.Restore.Inputs.Length == 0 || contract.Restore.Outputs.Length == 0)
        {
            throw new InvalidDataException("Prepared Restore requires explicit complete input and output lists");
        }
        var inputs = contract.Restore.Inputs.ToHashSet(StringComparer.Ordinal);
        if ((contract.DefinitionDigests ?? []).Keys.Concat(contract.SharedInputs).Concat(contract.Projects.Keys).Any(path => !inputs.Contains(path)))
        {
            throw new InvalidDataException("Restore inputs must include every project, definition and shared input");
        }
        foreach (var path in contract.Restore.Inputs.Concat(contract.Restore.Outputs))
        {
            files.Resolve(path);
        }
        if (contract.Restore.Outputs.Any(path => inputs.Contains(path) || path.StartsWith(".package-source/", StringComparison.Ordinal) || path.StartsWith(".graph-tools/", StringComparison.Ordinal)))
        {
            throw new InvalidDataException("Restore outputs must not overwrite authored inputs or tools");
        }
    }

    private static string Key(GraphContract contract, ContractFiles files, string sdkDigest)
    {
        var records = new List<string> { "graph-restore-v1", files.Root, files.Sdk, sdkDigest,
            ContractFiles.Digest(typeof(PreparedRestore).Assembly.Location), JsonSerializer.Serialize(contract) };
        records.AddRange(contract.Restore!.Inputs.Distinct().Order(StringComparer.Ordinal)
            .Select(path => path + ":" + ContractFiles.InputDigest(files.Resolve(path))));
        var packages = Path.Combine(files.Root, ".package-source");
        records.AddRange(Directory.Exists(packages) ? Directory.GetFiles(packages, "*.nupkg").Order(StringComparer.Ordinal)
            .Select(path => Path.GetFileName(path) + ":" + ContractFiles.InputDigest(path)) : []);
        records.AddRange(Environment.GetEnvironmentVariables().Cast<System.Collections.DictionaryEntry>()
            .OrderBy(pair => (string)pair.Key, StringComparer.Ordinal).Select(pair => pair.Key + "=" + pair.Value));
        return ContractFiles.Hash(records);
    }
}
