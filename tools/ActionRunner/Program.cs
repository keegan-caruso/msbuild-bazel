using ActionRunner;

try
{
    if (args.Length != 2 || args[0] != "--request")
        throw new ArgumentException("usage: dotnet ActionRunner.dll --request PATH");
    var request = JsonFiles.ReadRequest(args[1]);
    NativeRuntimeInputs.Validate(request);
    var workspace = new Workspace(request);
    workspace.Stage(request);
    if (request.GraphProject is not null)
    {
        await GraphAction.RunAsync(request, workspace);
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
