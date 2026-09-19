using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

internal static class Program
{
    public static int Main(string[] args)
    {
        try
        {
            if (args.Length == 1 && args[0] == "workflow-session")
            {
                var store = new ProtectedStore();
                var controllerDirectory = Host.Real(AppContext.BaseDirectory); var controllerIdentity = FileTree.Snapshot(controllerDirectory);
                string? line;
                while ((line = Console.ReadLine()) is not null)
                {
                    try
                    {
                        FileTree.Verify(controllerDirectory, controllerIdentity);
                        var sessionRequest = JsonNode.Parse(line) ?? throw new InvalidDataException("Empty request");
                        var report = NativeWorkflow.Run(sessionRequest, store);
                        Console.WriteLine(report.ToJsonString());
                    }
                    catch (Exception error) { Console.WriteLine(new JsonObject { ["accepted"] = false, ["error"] = error.Message }.ToJsonString()); }
                }
                return 0;
            }
            if (args.Length > 0 && args[0] == "tooling") { Tooling.Run(args[1..]); return 0; }
            if (args.Length > 0 && args[0] == "workflow" && !(args.Length == 3 && args[1] == "--request"))
            {
                Console.WriteLine(Json.Text(NativeWorkflow.Run(NativeWorkflow.Arguments(args[1..]))));
                return 0;
            }
            if (args.Length == 0) throw new ArgumentException("Usage: Preparation <prepare|digest> --request <file>");
            if (args.Length != 3 || args[1] != "--request") throw new ArgumentException("Expected --request <file>");
            var request = JsonNode.Parse(File.ReadAllText(args[2])) ?? throw new InvalidDataException("Empty request");
            switch (args[0])
            {
                case "owned-extract-package": PackageExtraction.Run(request); break;
                case "owned-validate-layout": ProjectLayout.Validate(request); break;
                case "owned-export-layout": Json.Write(request.String("output"), ProjectLayout.Capture(Json.Read(request.String("graph")))); break;
                case "owned-locked-restore": LockedRestore.Run(request); break;
                case "owned-normalize-restore": RestoreInputs.Run(request); break;
                case "owned-workflow": Console.WriteLine(Json.Text(BazelOwnedWorkflow.Run(request))); break;
                case "owned-bind-sources": NativePlan.BindSources(request); break;
                case "owned-prepare": BazelOwnedWorkflow.Prepare(request); break;
                case "digest": Console.WriteLine(Json.Digest(request)); break;
                case "workflow": Console.WriteLine(Json.Text(NativeWorkflow.Run(request))); break;
                case "prepare": GraphPreparation.Run(request); break;
                default: throw new ArgumentException("Unknown command: " + args[0]);
            }
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(Environment.GetEnvironmentVariable("RULES_MSBUILD_TRACE") == "1" ? error.ToString() : error.Message);
            return 1;
        }
    }
}
