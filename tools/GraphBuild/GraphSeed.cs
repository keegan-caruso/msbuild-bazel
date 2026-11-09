using System.Text.Json;
using RulesMSBuild.ProjectCache;

namespace RulesMSBuild.GraphBuild;

internal static class GraphSeed
{
    internal static async Task<int> Run(string[] args, GraphRunOptions options)
    {
        if (args.Length != 5 || !OperatingSystem.IsLinux() || args[0] != BuildSeedProof.Root ||
            Environment.GetEnvironmentVariable("DOTNET_ROOT") != BuildSeedProof.Sdk)
        {
            throw new InvalidDataException("Graph cache seeding requires the canonical Linux qualification context: ROOT CONTRACT REPORT CACHE PROOF");
        }
        var timer = System.Diagnostics.Stopwatch.StartNew();
        var root = args[0];
        Directory.SetCurrentDirectory(root);
        var contract = JsonSerializer.Deserialize<GraphContract>(File.ReadAllText(args[1]))!;
        var seed = JsonSerializer.Deserialize<BuildSeed>(File.ReadAllText(args[4]))!;
        if (seed.Version != 1 || seed.Root != root || seed.Sdk != BuildSeedProof.Sdk || seed.SdkDigest != BuildSeedProof.TreeDigest(seed.Sdk))
        {
            throw new InvalidDataException("Qualification seed SDK or namespace changed");
        }
        var sdk = Path.Combine(seed.Sdk, "sdk", contract.SdkVersion);
        MSBuildContext.Bind(sdk);
        Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(sdk, "MSBuild.dll"));
        Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(sdk, "Sdks"));
        Environment.SetEnvironmentVariable("DOTNET_HOST_PATH", Path.Combine(seed.Sdk, "dotnet"));
        Environment.SetEnvironmentVariable("NUGET_PACKAGES", Path.Combine(root, ".nuget"));
        contract = GraphTools.Bind(contract, root, seed.Sdk);
        GraphDirectories.Prepare(contract, new ContractFiles(root, seed.Sdk), create: false);
        // Qualification already restored this closed inventory. Use those verified
        // bytes, exactly as an ordinary prepared-Restore consumer does. A normal
        // consumer still keys its own Restore products before accepting a hit.
        var packages = Path.Combine(root, ".nuget");
        contract = contract with
        {
            SharedInputs = contract.SharedInputs.Concat(Directory.Exists(packages)
                ? Directory.EnumerateFiles(packages, "*", SearchOption.AllDirectories).Select(path => Path.GetRelativePath(root, path)) : []).ToArray()
        };
        foreach (var (relative, digest) in seed.Inputs)
        {
            var path = new ContractFiles(root, seed.Sdk).Resolve(relative);
            if (!File.Exists(path) || BuildSeedProof.Digest(path) != digest)
            {
                throw new InvalidDataException("Qualification seed input changed during handoff: " + relative);
            }
        }
        foreach (var (relative, digest) in seed.Outputs)
        {
            var path = new ContractFiles(root, seed.Sdk).Resolve(relative);
            if (!File.Exists(path) || BuildSeedProof.Digest(path) != digest)
            {
                throw new InvalidDataException("Qualification seed output changed: " + relative);
            }
        }
        using var inputs = Evaluate(contract, seed);
        inputs.VerifySeedInputs(seed);
        var payloads = new SnapshotPayloads(args[3]);
        using var remote = options.RemoteUrl is null ? null : new RemoteSnapshotStore(new Uri(options.RemoteUrl.TrimEnd('/') + "/"),
            bearerToken: options.BearerToken, contentStore: payloads);
        var plugin = new GraphCache(inputs, args[3], false, remote, new FileMaterializer(false, false), payloads, new TemporaryOutputs(contract, inputs));
        var seeded = await plugin.SeedAsync(seed);
        File.WriteAllText(args[2], JsonSerializer.Serialize(new
        {
            seeded,
            seconds = timer.Elapsed.TotalSeconds
        }));
        Console.Error.WriteLine("GRAPH_CACHE_SEED " + File.ReadAllText(args[2]));
        return 0;
    }

    private static GraphInputs Evaluate(GraphContract contract, BuildSeed seed)
    {
        // A fresh ordinary build evaluates before compiler products exist. Keep
        // qualified products beside the workspace during that pristine pass;
        // Exists() and globs must not acquire new generated inputs after Build.
        var files = new ContractFiles(seed.Root, seed.Sdk);
        var staging = Path.Combine(Path.GetDirectoryName(seed.Root)!, ".seed-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(staging);
        var moved = new List<string>();
        try
        {
            foreach (var relative in seed.Outputs.Keys.Except(seed.Inputs.Keys, StringComparer.Ordinal))
            {
                var source = files.Resolve(relative);
                var destination = Path.Combine(staging, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
                File.Move(source, destination);
                moved.Add(relative);
            }
            return new GraphInputs(contract, seed.Root, seed.Sdk, restored: true);
        }
        finally
        {
            foreach (var relative in moved)
            {
                var destination = files.Resolve(relative);
                if (File.Exists(destination))
                {
                    throw new InvalidDataException("Evaluation wrote a qualification output: " + relative);
                }
                Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
                File.Move(Path.Combine(staging, relative), destination);
            }
            Directory.Delete(staging, recursive: true);
        }
    }

}
