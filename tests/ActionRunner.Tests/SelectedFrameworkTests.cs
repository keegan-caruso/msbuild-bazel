using System.Xml.Linq;
using ActionRunner;

internal static class SelectedFrameworkTests
{
    public static void Run(ActionRequest baseline, string root)
    {
        var request = baseline with
        {
            GraphProject = "App/App.csproj",
            Output = Path.Combine(root, "selected-output"),
            Diagnostics = Path.Combine(root, "selected-diagnostics"),
            GraphFrameworkSelections = new()
            {
                ["App/App.csproj"] = new("net10.0", new() { ["Shared/Shared.csproj"] = "net10.0" }),
                ["Shared/Shared.csproj"] = new("net10.0", new())
            }
        };
        var workspace = new Workspace(request);
        var path = SelectedFrameworks.Stage(request, workspace)!;
        var document = XDocument.Load(path);
        if (document.Descendants("TargetFrameworks").Any() || document.Descendants("TargetFramework").Any() ||
            document.Descendants("InnerBuildProperty").Count() != 2 ||
            !document.Descendants("ProjectReference").Any(item => (string?)item.Attribute("Update") == "../Shared/Shared.csproj" && (string?)item.Element("SetTargetFramework") == "TargetFramework=net10.0"))
            throw new InvalidOperationException("selected framework import changed source declaration or lost edge");
        request.GraphFrameworkSelections["App/App.csproj"].References["Shared/Shared.csproj"] = "netstandard2.0";
        request.GraphFrameworkSelections["Shared/Shared.csproj"] = new("netstandard2.0", new(), RemoveFrameworkGlobal: true);
        document = XDocument.Load(SelectedFrameworks.Stage(request, workspace)!);
        if (!document.Descendants("ProjectReference").Any(item => (string?)item.Element("SetTargetFramework") == "TargetFramework=netstandard2.0") ||
            !document.Descendants("PropertyGroup").Any(item => ((string?)item.Attribute("Condition"))?.EndsWith("'$(TargetFramework)' == 'netstandard2.0'", StringComparison.Ordinal) == true) ||
            document.Descendants("TargetFramework").Any())
            throw new InvalidOperationException("mixed selected framework edge or condition lost");
        if (!document.Descendants("ProjectReference").Any(item =>
            (string?)item.Element("GlobalPropertiesToRemove") == "%(ProjectReference.GlobalPropertiesToRemove);TargetFramework"))
            throw new InvalidOperationException("implicit child framework global removal missing");
        request.GraphFrameworkSelections["App/App.csproj"].References["Shared/Shared.csproj"] = "netstandard2.1";
        request.GraphFrameworkSelections["Shared/Shared.csproj"] = new("netstandard2.1", new());
        try
        {
            SelectedFrameworks.Stage(request, workspace);
            throw new InvalidOperationException("unsupported selected framework accepted");
        }
        catch (InvalidDataException error) when (error.Message == "selected framework project invalid") { }
        request.GraphFrameworkSelections["Shared/Shared.csproj"] = new("netstandard2.0", new(), RemoveFrameworkGlobal: true);
        request.GraphFrameworkSelections["App/App.csproj"].References["Shared/Shared.csproj"] = "netstandard2.0";
        request.GraphFrameworkSelections["App/App.csproj"].References["Missing/Missing.csproj"] = "net10.0";
        try
        {
            SelectedFrameworks.Stage(request, workspace);
            throw new InvalidOperationException("missing selected dependency accepted");
        }
        catch (InvalidDataException error) when (error.Message == "selected framework dependency invalid") { }
    }
}
