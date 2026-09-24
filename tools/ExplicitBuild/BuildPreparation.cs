using static Program;

internal static class BuildPreparation
{
    internal static Session Prepare(Request r, string workspace, string state, Func<string, string>? compilerPath = null, string[]? analyzerRoots = null)
    {
        compilerPath ??= path => path;
        Safe(r.Assembly);
        FrameworkReferences.Validate(r);
        if (r.Assembly.Contains('/'))
        {
            throw new InvalidDataException("Assembly name must be a filename");
        }

        Directory.CreateDirectory(workspace);
        Directory.CreateDirectory(state);
        foreach (var directory in r.Directories ?? [])
        {
            Directory.CreateDirectory(Path.Combine(workspace, Safe(directory)));
        }

        foreach (var file in r.Sources.Concat(r.Imports).Concat(r.AdapterImports ?? []).Concat(r.Items.Select(i => i.File)).Prepend(r.Project))
        {
            Copy(ReadPath(file.Source), Path.Combine(workspace, Safe(file.Path)));
        }

        var references = Path.Combine(workspace, ".references");
        Directory.CreateDirectory(references);
        foreach (var reference in r.References)
        {
            Copy(ReadPath(reference), Path.Combine(references, Path.GetFileName(reference)));
        }

        foreach (var reference in r.RuntimeReferences ?? [])
        {
            Copy(ReadPath(reference), Path.Combine(workspace, ".runtime-references", Path.GetFileName(reference)));
        }

        ArtifactLayouts.Stage(r, workspace);
        ProjectAnalyzers.Stage(r, workspace, analyzerRoots);
        BuildTools.Stage(r, workspace);
        ProjectOutputs.Stage(r, workspace);
        var project = Path.Combine(workspace, Safe(r.Project.Path));
        var original = Path.Combine(state, "original.xml");
        File.Copy(project, original);
        if (r.RestoreInput is not null || r.RestoreOnly)
        {
            PreparedRestore.Validate(r, original);
        }

        var packageRoot = Path.Combine(workspace, ".nuget", "packages");
        Directory.CreateDirectory(packageRoot);
        foreach (var package in r.Packages)
        {
            var target = Path.Combine(packageRoot, Safe(package.Id.ToLowerInvariant()), Safe(package.Version));
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            Directory.CreateSymbolicLink(target, compilerPath(Real(package.Directory)));
        }
        var config = Path.Combine(workspace, "NuGet.Config");
        if (File.Exists(config))
        {
            throw new InvalidDataException("Explicit builds supply their own closed NuGet configuration");
        }

        File.WriteAllText(config, "<configuration><packageSources><clear /></packageSources></configuration>");
        if (!OperatingSystem.IsWindows())
        {
            File.SetUnixFileMode(project, UnixFileMode.UserRead | UnixFileMode.UserWrite);
        }

        ProjectDefinition.Write(r, project, references, compilerPath, analyzerRoots);
        var session = new Session(r, workspace, state, original, Real(Path.GetDirectoryName(Environment.ProcessPath!)!), Real(AppContext.BaseDirectory.TrimEnd('/')));
        if (r.RestoreInput is not null)
        {
            PreparedRestore.Install(session, compilerPath);
        }

        return session;
    }
}
