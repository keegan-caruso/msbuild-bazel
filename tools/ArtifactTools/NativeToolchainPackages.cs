using System.Diagnostics;
using System.Formats.Tar;
using System.Runtime.Versioning;
using System.Security.Cryptography;

internal sealed record NativeToolchainPackage(string Name, string Archive, string Sha256, string LicensePath);
internal sealed record NativeToolchainPackagesRequest(NativeToolchainPackage[] Packages, string? Manifest, string Output, Dictionary<string, string>? Symlinks = null, string[]? ExcludePrefixes = null, string? Archive = null);

internal static class NativeToolchainPackages
{
    internal static void Assemble(NativeToolchainPackagesRequest request)
    {
        if (!OperatingSystem.IsLinux())
        {
            throw new PlatformNotSupportedException("Native AOT package assembly currently requires Linux");
        }

        var complete = request.Manifest is null;
        var excluded = (request.ExcludePrefixes ?? []).Select(Program.Safe).ToArray();
        if (!complete && excluded.Length != 0)
        {
            throw new InvalidDataException("Native toolchain manifest and excluded directories are mutually exclusive");
        }
        var retained = complete ? [] : File.ReadAllLines(request.Manifest!).Where(line => line.Length > 0).ToArray();
        if (!complete && (retained.Length == 0 || !retained.SequenceEqual(retained.Order(StringComparer.Ordinal), StringComparer.Ordinal) || retained.Distinct(StringComparer.Ordinal).Count() != retained.Length))
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
        var notices = new HashSet<string>(StringComparer.Ordinal);
        foreach (var package in request.Packages)
        {
            var path = Program.Safe(package.LicensePath);
            while (path.Length != 0)
            {
                notices.Add(path);
                path = Path.GetDirectoryName(path) ?? "";
            }
        }
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
                    CopySelected(entry, output, selected, copied, complete, excluded, notices);
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

        foreach (var (relative, target) in request.Symlinks ?? [])
        {
            Program.Safe(relative);
            Program.Safe(target);
            if (!relative.StartsWith("usr/", StringComparison.Ordinal) && !relative.StartsWith("etc/", StringComparison.Ordinal))
            {
                throw new InvalidDataException("Native toolchain aliases must be under usr or etc: " + relative);
            }
            var destination = Path.Combine(output, relative);
            var parent = Path.GetDirectoryName(destination)!;
            EnsureDirectory(output, parent);
            if (File.Exists(destination) || Directory.Exists(destination) || new FileInfo(destination).LinkTarget is not null)
            {
                throw new InvalidDataException("Duplicate native toolchain alias: " + relative);
            }
            File.CreateSymbolicLink(destination, Path.GetRelativePath(parent, Path.Combine(output, target)));
            copied.Add(relative);
        }

        foreach (var package in request.Packages)
        {
            if (!File.Exists(Path.Combine(output, package.LicensePath)))
            {
                throw new InvalidDataException("Native package copyright notice is missing: " + package.Name);
            }
        }

        foreach (var relative in copied)
        {
            var path = Path.Combine(output, relative);
            var info = new FileInfo(path);
            if (info.LinkTarget is null)
            {
                continue;
            }

            var resolved = info.ResolveLinkTarget(returnFinalTarget: true);
            var relativeTarget = resolved is null ? ".." : Path.GetRelativePath(output, resolved.FullName);
            if (relativeTarget is ".." || relativeTarget.StartsWith("../", StringComparison.Ordinal) || resolved is null || !File.Exists(resolved.FullName) && !Directory.Exists(resolved.FullName))
            {
                throw new InvalidDataException("Native toolchain link escapes or is dangling: " + relative);
            }
        }

        // Package paths under /lib are merged into usr/lib above. GNU linker
        // scripts retain absolute /lib references, which would escape this
        // declared sysroot unless their paths use the same mapping.
        foreach (var relative in copied.Where(path => path.EndsWith(".so", StringComparison.Ordinal)))
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
        if (request.Archive is not null)
        {
            NativeToolchainArchive.Write(output, request.Archive);
        }
    }

    [SupportedOSPlatform("linux")]
    private static void CopySelected(TarEntry entry, string output, HashSet<string> selected, HashSet<string> copied, bool complete, string[] excluded, HashSet<string> notices)
    {
        var source = (entry.Name.StartsWith("./", StringComparison.Ordinal) ? entry.Name[2..] : entry.Name).TrimEnd('/');
        if (source.Length == 0 || source == ".")
        {
            return;
        }

        Program.Safe(source);
        var relative = Map(source);
        if (!notices.Contains(relative) && excluded.Any(prefix => relative == prefix || relative.StartsWith(prefix + "/", StringComparison.Ordinal)))
        {
            return;
        }
        if (entry.EntryType == TarEntryType.Directory)
        {
            if (complete && (relative is "usr" or "etc" || relative.StartsWith("usr/", StringComparison.Ordinal) || relative.StartsWith("etc/", StringComparison.Ordinal)))
            {
                EnsureDirectory(output, Path.Combine(output, relative));
            }
            return;
        }
        if (complete && (relative.StartsWith("usr/", StringComparison.Ordinal) || relative.StartsWith("etc/", StringComparison.Ordinal)))
        {
            selected.Add(relative);
        }
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
        else if (entry.EntryType == TarEntryType.HardLink)
        {
            var link = entry.LinkName ?? throw new InvalidDataException("Native package hardlink lacks a target: " + relative);
            var target = Map(Program.Safe(link.StartsWith("./", StringComparison.Ordinal) ? link[2..] : link));
            File.Copy(Path.Combine(output, target), destination);
        }
        else if (entry.EntryType is TarEntryType.RegularFile or TarEntryType.V7RegularFile)
        {
            using var file = File.Create(destination);
            if (entry.DataStream is { } data)
            {
                data.CopyTo(file);
            }
            else if (entry.Length != 0)
            {
                throw new InvalidDataException("Native package file lacks data: " + relative);
            }
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
