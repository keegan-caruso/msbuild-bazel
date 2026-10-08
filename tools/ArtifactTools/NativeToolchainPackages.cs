using System.Diagnostics;
using System.Formats.Tar;
using System.Runtime.Versioning;
using System.Security.Cryptography;

internal sealed record NativeToolchainPackage(string Name, string Archive, string Sha256, string LicensePath);
internal sealed record NativeToolchainPackagesRequest(NativeToolchainPackage[] Packages, string Manifest, string Output);

internal static class NativeToolchainPackages
{
    internal static void Assemble(NativeToolchainPackagesRequest request)
    {
        if (!OperatingSystem.IsLinux())
        {
            throw new PlatformNotSupportedException("Native AOT package assembly currently requires Linux");
        }

        var retained = File.ReadAllLines(request.Manifest).Where(line => line.Length > 0).ToArray();
        if (retained.Length == 0 || !retained.SequenceEqual(retained.Order(StringComparer.Ordinal), StringComparer.Ordinal) || retained.Distinct(StringComparer.Ordinal).Count() != retained.Length)
        {
            throw new InvalidDataException("Native toolchain file manifest must be nonempty, sorted and unique");
        }

        foreach (var path in retained)
        {
            Program.Safe(path);
            if (!path.StartsWith("usr/", StringComparison.Ordinal) && !path.StartsWith("etc/", StringComparison.Ordinal))
            {
                throw new InvalidDataException("Native toolchain files must be under usr or etc: " + path);
            }
        }

        if (request.Packages.Length == 0 || request.Packages.Select(p => p.Name).Distinct(StringComparer.Ordinal).Count() != request.Packages.Length)
        {
            throw new InvalidDataException("Native toolchain packages must be nonempty and uniquely named");
        }

        var selected = retained.ToHashSet(StringComparer.Ordinal);
        var copied = new HashSet<string>(StringComparer.Ordinal);
        var output = Path.GetFullPath(request.Output);
        Directory.CreateDirectory(output);
        foreach (var package in request.Packages)
        {
            Program.Safe(package.Name);
            Program.Safe(package.LicensePath);
            if (package.Sha256.Length != 64 || !package.Sha256.All(Uri.IsHexDigit))
            {
                throw new InvalidDataException("Invalid SHA-256 for native package " + package.Name);
            }

            using (var stream = File.OpenRead(package.Archive))
            {
                var actual = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
                if (!actual.Equals(package.Sha256, StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidDataException("Native package differs from locked SHA-256: " + package.Name);
                }
            }

            var extract = new ProcessStartInfo("/usr/bin/dpkg-deb") { RedirectStandardOutput = true, RedirectStandardError = true };
            extract.ArgumentList.Add("--fsys-tarfile");
            extract.ArgumentList.Add(Path.GetFullPath(package.Archive));
            using var process = Process.Start(extract) ?? throw new InvalidDataException("Could not start dpkg-deb");
            var errorTask = process.StandardError.ReadToEndAsync();
            var outputStream = process.StandardOutput.BaseStream;
            using (var tar = new TarReader(outputStream, leaveOpen: true))
            {
                while (tar.GetNextEntry() is { } entry)
                {
                    CopySelected(entry, output, selected, copied);
                }
            }

            // TarReader stops at the archive end marker; dpkg-deb may still
            // write padding. Drain the pipe before closing it.
            outputStream.CopyTo(Stream.Null);

            process.WaitForExit();
            if (process.ExitCode != 0)
            {
                throw new InvalidDataException("Could not read native package " + package.Name + ": " + errorTask.Result);
            }
        }

        if (!copied.SetEquals(selected))
        {
            throw new InvalidDataException("Native toolchain packages omit manifest files: " + string.Join(", ", selected.Except(copied).Take(8)));
        }

        foreach (var package in request.Packages)
        {
            if (!File.Exists(Path.Combine(output, package.LicensePath)))
            {
                throw new InvalidDataException("Native package copyright notice is missing: " + package.Name);
            }
        }

        foreach (var relative in retained)
        {
            var path = Path.Combine(output, relative);
            var info = new FileInfo(path);
            if (info.LinkTarget is null)
            {
                continue;
            }

            var resolved = info.ResolveLinkTarget(returnFinalTarget: true);
            var relativeTarget = resolved is null ? ".." : Path.GetRelativePath(output, resolved.FullName);
            if (relativeTarget is ".." || relativeTarget.StartsWith("../", StringComparison.Ordinal) || !File.Exists(path) && !Directory.Exists(path))
            {
                throw new InvalidDataException("Native toolchain link escapes or is dangling: " + relative);
            }
        }

        // Package paths under /lib are merged into usr/lib above. GNU linker
        // scripts retain absolute /lib references, which would escape this
        // declared sysroot unless their paths use the same mapping.
        foreach (var relative in retained.Where(path => path.EndsWith(".so", StringComparison.Ordinal)))
        {
            var path = Path.Combine(output, relative);
            using var stream = File.OpenRead(path);
            var prefix = new byte[16];
            if (stream.Read(prefix) != prefix.Length || !prefix.AsSpan().SequenceEqual("/* GNU ld script"u8))
            {
                continue;
            }

            stream.Close();
            var script = File.ReadAllText(path);
            File.WriteAllText(path, script.Replace(" /lib/", " /usr/lib/", StringComparison.Ordinal));
        }

        if (!Directory.Exists(Path.Combine(output, "usr")) || !Directory.Exists(Path.Combine(output, "etc")))
        {
            throw new InvalidDataException("Native toolchain packages must produce usr and etc directories");
        }
    }

    [SupportedOSPlatform("linux")]
    private static void CopySelected(TarEntry entry, string output, HashSet<string> selected, HashSet<string> copied)
    {
        var source = entry.Name.StartsWith("./", StringComparison.Ordinal) ? entry.Name[2..] : entry.Name;
        if (source.Length == 0 || entry.EntryType == TarEntryType.Directory)
        {
            return;
        }

        Program.Safe(source);
        var relative = Map(source);
        if (!selected.Contains(relative))
        {
            return;
        }

        var destination = Path.Combine(output, relative);
        var parent = Path.GetDirectoryName(destination)!;
        EnsureDirectory(output, parent);
        if (File.Exists(destination) || Directory.Exists(destination) || new FileInfo(destination).LinkTarget is not null)
        {
            throw new InvalidDataException("Duplicate native toolchain package file: " + relative);
        }

        if (entry.EntryType == TarEntryType.SymbolicLink)
        {
            var link = entry.LinkName ?? throw new InvalidDataException("Native package link lacks a target: " + relative);
            var rawTarget = link.StartsWith("/", StringComparison.Ordinal)
                ? link.TrimStart('/')
                : Path.GetRelativePath("/__pkgroot__", Path.GetFullPath(Path.Combine("/__pkgroot__", Path.GetDirectoryName(source)!, link))).Replace(Path.DirectorySeparatorChar, '/');
            if (rawTarget is ".." || rawTarget.StartsWith("../", StringComparison.Ordinal))
            {
                throw new InvalidDataException("Native package link escapes its root: " + relative);
            }

            var target = Path.Combine(output, Map(rawTarget));
            File.CreateSymbolicLink(destination, Path.GetRelativePath(parent, target));
        }
        else if (entry.EntryType is TarEntryType.RegularFile or TarEntryType.V7RegularFile)
        {
            using var file = File.Create(destination);
            entry.DataStream!.CopyTo(file);
            file.Close();
            File.SetUnixFileMode(destination, entry.Mode);
        }
        else
        {
            throw new InvalidDataException("Unsupported native package entry type: " + entry.EntryType);
        }

        copied.Add(relative);
    }

    private static void EnsureDirectory(string root, string path)
    {
        var relative = Path.GetRelativePath(root, path);
        var current = root;
        foreach (var part in relative.Split(Path.DirectorySeparatorChar))
        {
            current = Path.Combine(current, part);
            if (new DirectoryInfo(current).LinkTarget is not null)
            {
                throw new InvalidDataException("Native package would write through a directory link: " + current);
            }

            Directory.CreateDirectory(current);
        }
    }

    private static string Map(string path)
    {
        var pieces = path.Split('/', 2);
        return pieces[0] is "bin" or "lib" or "sbin" ? "usr/" + path : path;
    }
}
