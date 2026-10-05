namespace RulesMSBuild.GraphBuild;

internal static class MSBuildContext
{
    private static string? engine;

    internal static void Bind(string path)
    {
        if (engine is not null && engine != path)
        {
            throw new InvalidDataException("MSBuild SDK context changed; restart the graph process");
        }
        if (engine is null)
        {
            engine = path;
            System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (context, name) =>
                File.Exists(Path.Combine(engine, name.Name + ".dll")) ? context.LoadFromAssemblyPath(Path.Combine(engine, name.Name + ".dll")) : null;
        }
    }
}
