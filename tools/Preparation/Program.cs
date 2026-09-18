using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

internal static class Program
{
    public static int Main(string[] args)
    {
        try
        {
            if (args.Length == 0) throw new ArgumentException("Usage: Preparation <prepare|digest> --request <file>");
            if (args.Length != 3 || args[1] != "--request") throw new ArgumentException("Expected --request <file>");
            var request = JsonNode.Parse(File.ReadAllText(args[2])) ?? throw new InvalidDataException("Empty request");
            switch (args[0])
            {
                case "digest": Console.WriteLine(Json.Digest(request)); break;
                case "prepare": GraphPreparation.Run(request); break;
                default: throw new ArgumentException("Unknown command: " + args[0]);
            }
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
            return 1;
        }
    }
}
