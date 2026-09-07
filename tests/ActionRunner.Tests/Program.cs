using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using ActionRunner;

if (args is ["--child", var mode])
{
    switch (mode)
    {
        case "pipes":
            Console.Error.Write(new string('e', 262144));
            Console.Out.Write(new string('o', 262144));
            return 7;
        case "wait":
            await Task.Delay(TimeSpan.FromSeconds(60));
            return 0;
    }
}

static bool Check(bool condition, string message) =>
    condition ? true : throw new InvalidOperationException(message);

var directory = Directory.CreateTempSubdirectory("action-runner-tests-");
try
{
    const string validRequest = """
        {"project":"Shared","sources":[],"restore":[],"packages":[],"package_manifest":null,
         "plugin":"plugin.dll","build_props":"Action.props","build_targets":"Action.targets",
         "output":"bundle","diagnostics":"diagnostics","dependency":null,"undeclared_probe":"",
         "native_manifest":null,"native_files":[]}
        """;
    AssetRoleTests.Run();
    var payload = Path.Combine(directory.FullName, "payload.txt");
    File.WriteAllText(payload, "package payload");
    var link = Path.Combine(directory.FullName, "payload-link");
    File.CreateSymbolicLink(link, payload);
    Files.Verify(link, new FileInfo(payload).Length, Files.Hash(payload), "symlink payload rejected");
    try
    {
        Files.Verify(link, new FileInfo(payload).Length + 1, Files.Hash(payload), "wrong size rejected");
        throw new InvalidOperationException("wrong size accepted");
    }
    catch (InvalidDataException error) when (error.Message == "wrong size rejected") { }
    var requestPath = Path.Combine(directory.FullName, "request.json");
    File.WriteAllText(requestPath, validRequest);
    Check(JsonFiles.ReadRequest(requestPath).Project == ProjectKind.Shared, "valid request must preserve project identity");
    if (args is ["--pilot-package-inputs", var sourceWorkspace, var stagedDirectory])
    {
        PilotPackageTests.Run(JsonFiles.ReadRequest(requestPath), sourceWorkspace, stagedDirectory, directory.FullName);
        Console.WriteLine("Pinned package symlink and manifest controls passed.");
        return 0;
    }
    SelectedFrameworkTests.Run(JsonFiles.ReadRequest(requestPath), directory.FullName);
    var nativeManifest = Path.Combine(directory.FullName, "native.json");
    var nativeEntry = new Artifact("store/lib/native", new FileInfo(payload).Length, Files.Hash(payload));
    JsonFiles.Write(nativeManifest, new NativeManifest(2, [nativeEntry]));
    var nativeRequest = JsonFiles.ReadRequest(requestPath) with
    {
        NativeManifest = nativeManifest,
        NativeFiles = [new InputFile(link, nativeEntry.Path)]
    };
    NativeRuntimeInputs.Validate(nativeRequest);
    File.WriteAllText(payload, "Package payload"); // Same size, different hash.
    try
    {
        NativeRuntimeInputs.Validate(nativeRequest);
        throw new InvalidOperationException("corrupt native payload accepted");
    }
    catch (InvalidDataException error) when (error.Message.Contains("payload mismatch")) { }
    foreach (var invalidManifest in new[]
    {
        new NativeManifest(1, [nativeEntry]),
        new NativeManifest(2, [nativeEntry, nativeEntry]),
        new NativeManifest(2, []),
        new NativeManifest(2, [nativeEntry with { Path = "../escape" }])
    })
    {
        JsonFiles.Write(nativeManifest, invalidManifest);
        try
        {
            NativeRuntimeInputs.Validate(nativeRequest);
            throw new InvalidOperationException("invalid native manifest accepted");
        }
        catch (InvalidDataException error) when (error.Message.Contains("declaration mismatch")) { }
    }
    foreach (var malformed in new[]
    {
        validRequest.Replace("\"project\":\"Shared\",", ""),
        validRequest.Replace("\"sources\":[]", "\"sources\":null"),
        validRequest.Replace("\"Shared\"", "\"Unknown\""),
        validRequest.Replace("\"Shared\"", "0"),
        validRequest.Replace("\"sources\":[]", "\"sources\":[],\"sources\":[]")
    })
    {
        File.WriteAllText(requestPath, malformed);
        try
        {
            JsonFiles.ReadRequest(requestPath);
            throw new InvalidOperationException("malformed request accepted: " + malformed);
        }
        catch (JsonException) { }
    }

    ProcessStartInfo Child(string childMode) => new(
        Environment.ProcessPath!, [Assembly.GetExecutingAssembly().Location, "--child", childMode])
    {
        RedirectStandardOutput = true,
        RedirectStandardError = true,
        UseShellExecute = false
    };

    var pipes = await ProcessRunner.RunAsync(Child("pipes"), TimeSpan.FromSeconds(10));
    Check(pipes.ExitCode == 7 && !pipes.TimedOut, "child exit code lost");
    Check(pipes.StandardOutput == new string('o', 262144), "stdout truncated");
    Check(pipes.StandardError == new string('e', 262144), "stderr truncated");
    var timer = Stopwatch.StartNew();
    var expired = await ProcessRunner.RunAsync(Child("wait"), TimeSpan.FromMilliseconds(200));
    Check(expired.TimedOut && timer.Elapsed < TimeSpan.FromSeconds(10), "timeout did not terminate child promptly");
    using var cancellation = new CancellationTokenSource(TimeSpan.FromMilliseconds(200));
    try
    {
        await ProcessRunner.RunAsync(Child("wait"), TimeSpan.FromSeconds(10), cancellation.Token);
        throw new InvalidOperationException("cancellation was swallowed");
    }
    catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }

    var evidence = BuildEvidence.Parse("SPIKE_COMPILE:App\r\nSPIKE_REPLAY_HIT:Shared\r\nSPIKE_PACKAGE_TARGET:Shared\r\n");
    evidence.Verify(ProjectKind.App);
    Check(evidence.PackageTargets.SequenceEqual(["Shared"]), "CRLF marker parsing changed");
    try
    {
        BuildEvidence.Parse("SPIKE_COMPILE:Shared\nSPIKE_COMPILE:App\nSPIKE_REPLAY_HIT:Shared\n").Verify(ProjectKind.App);
        throw new InvalidOperationException("duplicate dependency compilation accepted");
    }
    catch (InvalidOperationException error) when (error.Message.StartsWith("unexpected project compilation:")) { }
    Console.WriteLine("Action runner contract and process tests passed.");
    return 0;
}
finally
{
    directory.Delete(recursive: true);
}
