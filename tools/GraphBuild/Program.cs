using RulesMSBuild.GraphBuild;

if (args.Length > 0 && args[0] == "seed")
{
    try
    {
        return await GraphSeed.Run(args[1..], GraphRunOptions.Read());
    }
    catch (Exception error)
    {
        Console.Error.WriteLine(error.Message);
        return 1;
    }
}
if (args.Length > 0 && args[0] == "worker")
{
    return await GraphWorker.Run(args[1..]);
}
if (args.Length > 0 && args[0] == "engine")
{
    return await GraphEngine.Run(args[1..], GraphRunOptions.Read());
}
return await GraphRunner.Run(args, GraphRunOptions.Read());
