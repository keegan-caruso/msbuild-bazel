using ActionRunner;

try
{
    if (args is ["--assemble-runtime", var runtimeRequest])
    {
        CompileBoundary.Assemble(JsonFiles.Read<RuntimeAssemblyRequest>(runtimeRequest));
        return 0;
    }
    if (args.Length != 2 || args[0] is not ("--request" or "--batch-request"))
        throw new ArgumentException("usage: dotnet ActionRunner.dll --request PATH");
    var request = JsonFiles.ReadRequest(args[1]);
    NativeRuntimeInputs.Validate(request);
    var workspace = new Workspace(request);
    workspace.Stage(request);
    if (args[0] == "--batch-request")
    {
        await BatchAction.RunAsync(request, workspace);
        return 0;
    }
    if (request.GraphProject is not null)
    {
        await GraphAction.RunAsync(request, workspace);
        if (request.ApiOutput is not null) CompileBoundary.Project(workspace.Output, request.ApiOutput);
        return 0;
    }
    var packages = PackageInputs.Stage(request, workspace.Root);
    var bundle = Bundles.StageDependency(request, workspace);
    await Msbuild.RunAsync(request, workspace, bundle, packages);
    Bundles.Export(request.Project, workspace);
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine(error);
    return 1;
}
