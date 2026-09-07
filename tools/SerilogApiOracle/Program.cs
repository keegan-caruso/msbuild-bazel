using PublicApiGenerator;
using System.Reflection;
using System.Text;

if (args.Length != 2) throw new ArgumentException("usage: SerilogApiOracle assembly.dll actual.txt");
var assembly = Assembly.LoadFrom(Path.GetFullPath(args[0]));
// Options from pinned upstream test/Serilog.ApprovalTests/ApiApprovalTests.cs.
var publicApi = assembly.GeneratePublicApi(new()
{
    IncludeAssemblyAttributes = false,
    ExcludeAttributes = ["System.Diagnostics.DebuggerDisplayAttribute"],
});
File.WriteAllText(args[1], publicApi, new UTF8Encoding(false));
