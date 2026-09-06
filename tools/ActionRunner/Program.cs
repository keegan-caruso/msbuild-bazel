using ActionRunner;

try
{
    if (args.Length != 2 || args[0] != "--request")
        throw new ArgumentException("usage: dotnet ActionRunner.dll --request PATH");
    var request = JsonFiles.ReadRequest(args[1]);
    if (request.Project is not "Shared" and not "App")
        throw new InvalidDataException("unsupported project: " + request.Project);
    InputValidation.NativeRuntime(request);
    var workspace = new Workspace(request);
    workspace.Stage(request);
    var packages = InputValidation.StagePackages(request, workspace.Root);
    workspace.ConfigureBuild(request.Plugin);
    var bundle = Bundles.StageDependency(request, workspace);
    await Msbuild.Run(request, workspace, bundle, packages);
    Bundles.Export(request.Project, workspace);
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine(error);
    return 1;
}
