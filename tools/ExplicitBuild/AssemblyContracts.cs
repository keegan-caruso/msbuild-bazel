using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Text.Json;

internal sealed record AssemblyPair(string Contract, string ContractIdentity, string ImplementationIdentity, string Output, string ContractRestore, string ImplementationRestore, string RestoreOutput, string? RestoreKey = null);
internal sealed record AssemblyIdentity(string Name, bool ReferenceOnly);

internal static class AssemblyContracts
{
    internal static void Export(string assembly, string output)
    {
        using var stream = File.OpenRead(assembly);
        using var pe = new PEReader(stream);
        var reader = pe.GetMetadataReader();
        var referenceOnly = false;
        foreach (var handle in reader.GetAssemblyDefinition().GetCustomAttributes())
        {
            var attribute = reader.GetCustomAttribute(handle);
            if (attribute.Constructor.Kind != HandleKind.MemberReference)
            {
                continue;
            }

            var parent = reader.GetMemberReference((MemberReferenceHandle)attribute.Constructor).Parent;
            if (parent.Kind != HandleKind.TypeReference)
            {
                continue;
            }

            var type = reader.GetTypeReference((TypeReferenceHandle)parent);
            referenceOnly |= reader.GetString(type.Namespace) == "System.Runtime.CompilerServices" && reader.GetString(type.Name) == "ReferenceAssemblyAttribute";
        }
        File.WriteAllText(output, JsonSerializer.Serialize(new AssemblyIdentity(AssemblyName.GetAssemblyName(assembly).FullName, referenceOnly), Program.Json));
    }
    internal static void ValidateSelections(AssemblySelection[] selections)
    {
        foreach (var selection in selections)
        {
            var selected = JsonSerializer.Deserialize<AssemblyIdentity>(File.ReadAllText(selection.Selected), Program.Json)!;
            var candidate = JsonSerializer.Deserialize<AssemblyIdentity>(File.ReadAllText(selection.Candidate), Program.Json)!;
            if (selected.Name != candidate.Name || selected.ReferenceOnly)
            {
                throw new InvalidDataException("Selected assembly identity differs from the configured dependency: " + selected.Name + " / " + candidate.Name);
            }
        }
    }
    internal static void Pair(AssemblyPair request)
    {
        var contract = JsonSerializer.Deserialize<AssemblyIdentity>(File.ReadAllText(request.ContractIdentity), Program.Json)!;
        var implementation = JsonSerializer.Deserialize<AssemblyIdentity>(File.ReadAllText(request.ImplementationIdentity), Program.Json)!;
        if (contract.Name != implementation.Name || implementation.ReferenceOnly)
        {
            throw new InvalidDataException("Contract/implementation assembly identity mismatch or reference-only implementation");
        }

        var contractRestore = JsonSerializer.Deserialize<RestoreProject>(File.ReadAllText(request.ContractRestore), Program.Json)!;
        var implementationRestore = JsonSerializer.Deserialize<RestoreProject>(File.ReadAllText(request.ImplementationRestore), Program.Json)!;
        var restore = implementationRestore with
        {
            ConfigurationKey = request.RestoreKey,
            RestoreFramework = contractRestore.RestoreFramework ?? contractRestore.Framework,
            FrameworkProperties = contractRestore.FrameworkProperties
        };
        File.WriteAllText(request.RestoreOutput, JsonSerializer.Serialize(restore, Program.Json));
        Program.Copy(request.Contract, request.Output);
    }
}
