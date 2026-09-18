using System.Diagnostics;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;

internal static class RuntimeContractTests
{
    internal static void Run()
    {
        var root = Directory.CreateTempSubdirectory("runtime-contract-tests-").FullName;
        try
        {
            var source = typeof(RuntimeContractTests).Assembly.Location;
            var first = Path.Combine(root, "first.dll"); var second = Path.Combine(root, "second.dll");
            RuntimeContract.Write(source, first); RuntimeContract.Write(first, second);
            if (!File.ReadAllBytes(first).SequenceEqual(File.ReadAllBytes(second))) throw new InvalidOperationException("Runtime contract is not idempotent");
            using var input = File.OpenRead(source); using var original = new PEReader(input);
            using var output = File.OpenRead(first); using var contract = new PEReader(output);
            var metadata = original.GetMetadataReader(); var projected = contract.GetMetadataReader();
            string[] References(MetadataReader reader) => reader.AssemblyReferences.Select(handle =>
            {
                var reference = reader.GetAssemblyReference(handle);
                return reader.GetString(reference.Name) + ":" + reference.Version + ":" + Convert.ToHexString(reader.GetBlobBytes(reference.PublicKeyOrToken));
            }).ToArray();
            if (!References(metadata).SequenceEqual(References(projected)) || projected.MethodDefinitions.Count != 0 || projected.TypeDefinitions.Count != 1)
                throw new InvalidOperationException("Runtime contract must retain assembly dependencies but no implementation");
            if (FileVersionInfo.GetVersionInfo(source).FileVersion != FileVersionInfo.GetVersionInfo(first).FileVersion)
                throw new InvalidOperationException("Runtime contract changed SDK-visible file version");
            var method = metadata.MethodDefinitions.Select(metadata.GetMethodDefinition).First(value => value.RelativeVirtualAddress != 0);
            var section = original.PEHeaders.SectionHeaders.Single(value => method.RelativeVirtualAddress >= value.VirtualAddress && method.RelativeVirtualAddress < value.VirtualAddress + value.VirtualSize);
            var bytes = File.ReadAllBytes(source); bytes[section.PointerToRawData + method.RelativeVirtualAddress - section.VirtualAddress + 4] ^= 1;
            var edited = Path.Combine(root, "edited.dll"); File.WriteAllBytes(edited, bytes); RuntimeContract.Write(edited, second);
            if (!File.ReadAllBytes(first).SequenceEqual(File.ReadAllBytes(second))) throw new InvalidOperationException("Method-body bytes leaked into runtime contract");
        }
        finally { Directory.Delete(root, true); }
    }
}
