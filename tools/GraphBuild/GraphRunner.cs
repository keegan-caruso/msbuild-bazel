using System.Text.Json;
using Microsoft.Build.Execution;
using Microsoft.Build.Graph;
#if STABLE_PROJECT_CACHE
using Microsoft.Build.ProjectCache;
#else
using Microsoft.Build.Experimental.ProjectCache;
#endif
using RulesMSBuild.ProjectCache;

namespace RulesMSBuild.GraphBuild;

internal static class GraphRunner
{
    internal static async Task<int> Run(string[] args, GraphRunOptions options, EvaluationSession? evaluation = null)
    {
        if (args.Length < 4 || args[0] is not ("inspect" or "build" or "action" or "prepare"))
        {
            Console.Error.WriteLine("Usage: GraphBuild inspect ROOT CONTRACT REPORT | prepare ROOT CONTRACT REPORT OUTPUT | build/action ROOT CONTRACT REPORT CACHE [TARGET] [no-read]");
            return 2;
        }
        var remoteUrl = options.RemoteUrl;
        var bearerToken = options.BearerToken;
        var localStatePath = options.LocalState;
        var preparedPath = options.Prepared;
        var readOnlyPackages = options.ReadOnlyPackages;
        var profile = options.Profile;
        var copyMode = options.CopyMode;
        if (localStatePath is not null && args[0] is not ("build" or "action"))
        {
            throw new InvalidDataException("Retained state supports build/action only");
        }
        if (readOnlyPackages && (preparedPath is null || args[0] != "action"))
        {
            throw new InvalidDataException("Read-only packages require a prepared graph action");
        }
        GraphProfile.Reset(profile, options.EvaluationProfile);
        var totalTimer = System.Diagnostics.Stopwatch.StartNew();
        var root = args[1];
        var contractPath = args[2];
        var report = args[3];
        var cache = args.Length > 4 ? Path.GetFullPath(args[4]) : null;
        var contract = JsonSerializer.Deserialize<GraphContract>(File.ReadAllText(contractPath))
            ?? throw new InvalidDataException("Missing graph contract");
        report = Path.GetFullPath(report);
        Directory.SetCurrentDirectory(root);
        root = Directory.GetCurrentDirectory();
        var sdkRoot = Environment.GetEnvironmentVariable("DOTNET_ROOT") ?? throw new InvalidDataException("DOTNET_ROOT is required");
        var contractFiles = new ContractFiles(root, sdkRoot);
        foreach (var (path, digest) in contract.DefinitionDigests ?? [])
        {
            var source = contractFiles.Resolve(path);
            if (!File.Exists(source) || ContractFiles.Digest(source) != digest)
            {
                throw new InvalidDataException("Graph definition changed; rerun sync: " + path);
            }
        }
        Environment.SetEnvironmentVariable("DOTNET_HOST_PATH", Path.Combine(sdkRoot, OperatingSystem.IsWindows() ? "dotnet.exe" : "dotnet"));
        var sdk = Path.Combine(sdkRoot, "sdk", contract.SdkVersion);
        MSBuildContext.Bind(sdk);
        Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(sdk, "MSBuild.dll"));
        Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(sdk, "Sdks"));
        // Resolve package SDKs and key preparation against the same owned package root.
        Environment.SetEnvironmentVariable("NUGET_PACKAGES", Path.Combine(root, ".nuget"));
        if (contract.EntryProperties?.Count > 0 && contract.Version is not (6 or 7 or 8 or 9 or 10 or 11))
        {
            throw new InvalidDataException("Entry properties require graph contract version 6, 7, 8, 9, 10 or 11");
        }
        RulesMSBuild.GraphEntryProperties.Validate(contract.Entries ?? [contract.Entry], contract.EntryProperties ?? [], (contract.ToolProperties ?? []).Keys);
        contract = GraphTools.Bind(contract, root, sdkRoot);
        using var localState = localStatePath is null ? null : new LocalGraphState(localStatePath, contract, contractFiles);
        GraphDirectories.Prepare(contract, contractFiles, create: args[0] is "action" or "prepare");
        if (args[0] == "prepare")
        {
            PreparedRestore.Create(contract, root, sdkRoot, cache ?? throw new InvalidDataException("Prepared output is required"));
            File.WriteAllText(report, JsonSerializer.Serialize(new
            {
                preparationSeconds = totalTimer.Elapsed.TotalSeconds
            }));
            return 0;
        }
        RestoredInputs? prepared = null;
        var restoreTimer = System.Diagnostics.Stopwatch.StartNew();
        if (args[0] == "action")
        {
            if (preparedPath is null)
            {
                contract = Restore.Run(contract, root, sdkRoot);
            }
            else
            {
                prepared = PreparedRestore.Apply(contract, root, sdkRoot, preparedPath, readOnlyPackages);
                contract = prepared.Contract;
            }
        }
        restoreTimer.Stop();
        using var inputs = new GraphInputs(contract, root, sdkRoot, restored: args[0] == "action", prepared: prepared, evaluation: evaluation);
        if (args[0] is "build" or "action")
        {
            var target = args.Length > 5 ? args[5] : "Build";
            TemporaryOutputs temporaryOutputs;
            using (GraphProfile.Measure("temporaryOutputValidation"))
            {
                temporaryOutputs = new TemporaryOutputs(contract, inputs);
            }
            if (target is not ("Build" or "Pack" or "Publish"))
            {
                throw new InvalidDataException("The graph runner currently qualifies Build, Pack and Publish; execute tests through Bazel test actions");
            }
            localState?.Prepare(inputs, target);
            foreach (var directory in inputs.Graph.ProjectNodes.SelectMany(inputs.OutputDirectories))
            {
                if (localState is null && Directory.Exists(directory) && Directory.EnumerateFileSystemEntries(directory).Any())
                {
                    throw new InvalidDataException("Graph execution requires empty declared output directories: " + directory);
                }
            }
            foreach (var path in inputs.Graph.ProjectNodes.SelectMany(inputs.DeclaredOutputFiles))
            {
                if (localState is null && Path.Exists(path))
                {
                    throw new InvalidDataException("Graph execution requires absent declared output files: " + path);
                }
            }
            var timer = System.Diagnostics.Stopwatch.StartNew();
            var payloads = new SnapshotPayloads(cache ?? throw new InvalidDataException("Cache directory is required"));
            using var remote = remoteUrl is null ? null : new RemoteSnapshotStore(new Uri(remoteUrl.TrimEnd('/') + "/"), bearerToken: bearerToken, profile: profile, contentStore: payloads);
            var materializer = new FileMaterializer(copyMode == "clone", profile);
            var plugin = new GraphCache(inputs, cache ?? throw new InvalidDataException("Cache directory is required"), args.Length < 7 || args[6] != "no-read", remote, materializer, payloads, temporaryOutputs, localState);
            var buildEvaluation = profile || evaluation is not null ? new BuildEvaluationCounter() : null;
            var parameters = new BuildParameters(inputs.Collection)
            {
                MaxNodeCount = 4,
                EnableNodeReuse = false,
                DisableInProcNode = evaluation is not null,
                ProjectCacheDescriptor = ProjectCacheDescriptor.FromInstance(plugin),
                Loggers = [new Microsoft.Build.Logging.ConsoleLogger(Microsoft.Build.Framework.LoggerVerbosity.Minimal)],
            };
            if (buildEvaluation is not null)
            {
                parameters.Loggers = parameters.Loggers.Append(buildEvaluation);
            }
            if (profile)
            {
                parameters.Loggers = parameters.Loggers.Append(new Microsoft.Build.Logging.BinaryLogger
                {
                    Parameters = Path.ChangeExtension(report, ".binlog") + ";ProjectImports=None"
                });
            }
            using var manager = new BuildManager();
            var flags = inputs.Graph.ProjectNodes.Any(node => inputs.For(node).CompilerReferencesComplete)
                ? BuildRequestDataFlags.ProvideProjectStateAfterBuild : BuildRequestDataFlags.None;
            var result = manager.Build(parameters, new GraphBuildRequestData(inputs.Graph, [target], null, flags));
            if (result.OverallResult != BuildResultCode.Success)
            {
                Console.Error.WriteLine(result.Exception);
                foreach (var pair in result.ResultsByNode)
                {
                    Console.Error.WriteLine(pair.Key.ProjectInstance.FullPath + ": " + pair.Value.Exception);
                }
                return 1;
            }
            if (evaluation is not null && buildEvaluation!.Evaluations != 0)
            {
                throw new InvalidDataException("Retained graph build nodes unexpectedly reevaluated");
            }
            var executionSeconds = timer.Elapsed.TotalSeconds;
            var verificationTimer = System.Diagnostics.Stopwatch.StartNew();
            inputs.VerifyUnchangedInputs();
            var temporaryDirectoriesRemoved = temporaryOutputs.Discard(result);
            verificationTimer.Stop();
            var snapshotTimer = System.Diagnostics.Stopwatch.StartNew();
            await plugin.SaveAsync(result);
            plugin.DiscardReplayOmissions();
            snapshotTimer.Stop();
            localState?.Complete();
            File.WriteAllText(report, JsonSerializer.Serialize(new
            {
                materialization = materializer.Report,
                operations = GraphProfile.Report,
                evaluationProfile = inputs.EvaluationProfile,
                evaluationState = evaluation?.Report,
                remote = remote?.Report,
                restoreSeconds = restoreTimer.Elapsed.TotalSeconds,
                preparedRestore = prepared is not null,
                readOnlyPreparedPackages = prepared?.ReadOnlyPackages == true,
                retainedState = localState?.Reusable ?? false,
                executionSeconds,
                verificationSeconds = verificationTimer.Elapsed.TotalSeconds,
                temporaryDirectoriesRemoved,
                snapshotSeconds = snapshotTimer.Elapsed.TotalSeconds,
                hits = plugin.Hits,
                misses = plugin.Misses,
                buildAndSnapshotSeconds = timer.Elapsed.TotalSeconds,
                evaluationSeconds = inputs.EvaluationSeconds,
                buildNodeEvaluations = buildEvaluation?.Evaluations,
                inputHashSeconds = inputs.InputHashSeconds,
                totalSeconds = totalTimer.Elapsed.TotalSeconds
            }));
            return 0;
        }
        File.WriteAllText(report, JsonSerializer.Serialize(inputs.Graph.ProjectNodes.Select(node => new
        {
            project = inputs.Relative(node),
            properties = node.ProjectInstance.GlobalProperties,
            fingerprint = inputs.Fingerprint(node),
        }), new JsonSerializerOptions { WriteIndented = true }));
        return 0;
    }
}
