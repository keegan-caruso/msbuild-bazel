"""Generated output publication must not follow target-created links."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT / '.tools/dotnet'))


class GeneratedDirectoryLinks(unittest.TestCase):
    def test_file_and_directory_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>')
            (root / 'Program.cs').write_text('''
using System.Reflection;
using System.Text.Json;
var assembly = Assembly.LoadFrom(args[0]);
var request = JsonSerializer.Deserialize("{\\"GeneratedDirectories\\":{\\"App/Generated\\":\\"data\\"}}", assembly.GetType("Request")!);
var publish = assembly.GetType("GeneratedDirectories")!.GetMethod("Publish", BindingFlags.Static | BindingFlags.NonPublic)!;
var state = Path.Combine(args[1], "state");
var source = Path.Combine(state, "generated-directories", "App", "Generated");
Directory.CreateDirectory(source);
var secret = Path.Combine(args[1], "private.txt");
File.WriteAllText(secret, "must not escape");
for (var index = 0; index < 2; index++)
{
    var link = Path.Combine(source, "link");
    if (index == 0) File.CreateSymbolicLink(link, secret);
    else Directory.CreateSymbolicLink(link, args[1]);
    var runtime = Path.Combine(args[1], "runtime" + index);
    Directory.CreateDirectory(runtime);
    try
    {
        publish.Invoke(null, new[] {request, state, runtime});
        throw new Exception("Link was published");
    }
    catch (TargetInvocationException error) when (error.InnerException is InvalidDataException invalid && invalid.Message.Contains("contains a link")) {}
    if (Directory.EnumerateFiles(runtime, "*", SearchOption.AllDirectories).Any()) throw new Exception("Linked contents escaped");
    File.Delete(link);
}
Console.WriteLine("links rejected");
''')
            result = subprocess.run([str(SDK / 'dotnet'), 'run', '--project', str(root / 'Probe.csproj'), '-c', 'Release', '--', str(ROOT / 'tools/ExplicitBuild/bin/Release/net10.0/ExplicitBuild.dll'), str(root)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('links rejected', result.stdout)
