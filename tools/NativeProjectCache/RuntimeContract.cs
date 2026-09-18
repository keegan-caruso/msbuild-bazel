using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text;

// RAR reads implementation assembly references and Win32 version resources.
// Retain that metadata in a non-executable stub; compilation uses the separate
// genuine reference assembly and final runtime composition uses genuine DLLs.
internal static class RuntimeContract
{
    internal static void Write(string source, string destination)
    {
        using var stream = File.OpenRead(source); using var pe = new PEReader(stream);
        var reader = pe.GetMetadataReader(); var assembly = reader.GetAssemblyDefinition();
        var metadata = new MetadataBuilder();
        StringHandle Text(StringHandle handle) => metadata.GetOrAddString(reader.GetString(handle));
        BlobHandle Blob(BlobHandle handle) => metadata.GetOrAddBlob(reader.GetBlobBytes(handle));
        var identity = reader.GetString(assembly.Name) + ":" + assembly.Version + ":" + string.Join(';', reader.AssemblyReferences.Select(handle =>
        {
            var reference = reader.GetAssemblyReference(handle);
            return reader.GetString(reference.Name) + ":" + reference.Version + ":" + Convert.ToHexString(reader.GetBlobBytes(reference.PublicKeyOrToken));
        }));
        metadata.AddModule(0, metadata.GetOrAddString(reader.GetString(assembly.Name) + ".dll"), metadata.GetOrAddGuid(new Guid(SHA256.HashData(Encoding.UTF8.GetBytes(identity)).AsSpan(0, 16))), default, default);
        var definition = metadata.AddAssembly(Text(assembly.Name), assembly.Version, Text(assembly.Culture), Blob(assembly.PublicKey), assembly.Flags, assembly.HashAlgorithm);
        foreach (var handle in reader.AssemblyReferences)
        {
            var reference = reader.GetAssemblyReference(handle);
            metadata.AddAssemblyReference(Text(reference.Name), reference.Version, Text(reference.Culture), Blob(reference.PublicKeyOrToken), reference.Flags, Blob(reference.HashValue));
        }
        // Unix FileVersionInfo reads these managed attributes; RAR also uses
        // TargetFrameworkAttribute. Their constructors contain only strings.
        var attributes = new HashSet<string>(StringComparer.Ordinal)
        {
            "System.Reflection.AssemblyFileVersionAttribute", "System.Reflection.AssemblyInformationalVersionAttribute",
            "System.Reflection.AssemblyCompanyAttribute", "System.Reflection.AssemblyConfigurationAttribute",
            "System.Reflection.AssemblyDescriptionAttribute", "System.Reflection.AssemblyProductAttribute",
            "System.Reflection.AssemblyTitleAttribute", "System.Reflection.AssemblyTrademarkAttribute",
            "System.Reflection.AssemblyCopyrightAttribute", "System.Runtime.Versioning.TargetFrameworkAttribute"
        };
        foreach (var handle in assembly.GetCustomAttributes())
        {
            var attribute = reader.GetCustomAttribute(handle);
            if (attribute.Constructor.Kind != HandleKind.MemberReference) continue;
            var constructor = reader.GetMemberReference((MemberReferenceHandle)attribute.Constructor);
            if (constructor.Parent.Kind != HandleKind.TypeReference) continue;
            var type = reader.GetTypeReference((TypeReferenceHandle)constructor.Parent);
            if (!attributes.Contains(reader.GetString(type.Namespace) + "." + reader.GetString(type.Name))) continue;
            if (type.ResolutionScope.Kind != HandleKind.AssemblyReference) throw new InvalidDataException("Unsupported runtime attribute scope");
            var selected = metadata.AddTypeReference(type.ResolutionScope, Text(type.Namespace), Text(type.Name));
            var method = metadata.AddMemberReference(selected, Text(constructor.Name), Blob(constructor.Signature));
            metadata.AddCustomAttribute(definition, method, Blob(attribute.Value));
        }
        metadata.AddTypeDefinition(TypeAttributes.NotPublic, default, metadata.GetOrAddString("<Module>"), default, MetadataTokens.FieldDefinitionHandle(1), MetadataTokens.MethodDefinitionHandle(1));
        var resources = pe.PEHeaders.PEHeader!.ResourceTableDirectory;
        var resource = resources.Size == 0 ? null : new ResourceCopy(pe.GetSectionData(resources.RelativeVirtualAddress).GetContent(0, resources.Size).ToArray(), resources.RelativeVirtualAddress);
        var builder = new ManagedPEBuilder(new PEHeaderBuilder(machine: pe.PEHeaders.CoffHeader.Machine, imageCharacteristics: pe.PEHeaders.CoffHeader.Characteristics, subsystem: pe.PEHeaders.PEHeader.Subsystem), new MetadataRootBuilder(metadata), new BlobBuilder(), nativeResources: resource, flags: pe.PEHeaders.CorHeader!.Flags & ~CorFlags.StrongNameSigned, deterministicIdProvider: blobs => BlobContentId.FromHash(SHA256.HashData(blobs.SelectMany(blob => blob.GetBytes()).ToArray())));
        var bytes = new BlobBuilder(); builder.Serialize(bytes);
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!); File.WriteAllBytes(destination, bytes.ToArray());
    }
    private sealed class ResourceCopy(byte[] original, int originalRva) : ResourceSectionBuilder
    {
        protected override void Serialize(BlobBuilder builder, SectionLocation location)
        {
            var bytes = (byte[])original.Clone(); var visited = new HashSet<int>();
            void Visit(int offset)
            {
                if (!visited.Add(offset) || offset < 0 || offset + 16 > bytes.Length) throw new InvalidDataException("Invalid resource directory");
                var count = BitConverter.ToUInt16(bytes, offset + 12) + BitConverter.ToUInt16(bytes, offset + 14);
                for (var index = 0; index < count; index++)
                {
                    var position = offset + 16 + index * 8;
                    if (position + 8 > bytes.Length) throw new InvalidDataException("Invalid resource entry");
                    var target = BitConverter.ToUInt32(bytes, position + 4);
                    if ((target & 0x80000000) != 0) Visit((int)(target & 0x7fffffff));
                    else
                    {
                        if (target + 16 > bytes.Length) throw new InvalidDataException("Invalid resource data");
                        var value = BitConverter.ToInt32(bytes, (int)target);
                        if (value < originalRva || value - originalRva >= bytes.Length) throw new InvalidDataException("Resource data outside section");
                        BitConverter.GetBytes(checked(value - originalRva + location.RelativeVirtualAddress)).CopyTo(bytes, (int)target);
                    }
                }
            }
            Visit(0); builder.WriteBytes(bytes);
        }
    }
}
