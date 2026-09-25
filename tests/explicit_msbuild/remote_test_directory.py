"""A declared test directory relocates inputs without changing launcher staging."""
import argparse
from pathlib import Path
from remote_support import RemoteFixture

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path)
p.add_argument('--executor', required=True)
a = p.parse_args()
f = RemoteFixture(a.output, a.executor, instance='working-directory/' + a.output.name)
f.sdk()
f.put('Test.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup></Project>')
f.put('Program.cs', '''using System; using System.IO;
if (Path.GetFileName(Directory.GetCurrentDirectory()) != "tests") throw new Exception("wrong cwd");
if (File.ReadAllText("input.txt") != "declared input") throw new Exception("missing input");
File.WriteAllText("output/result.txt", "retained output");
Console.WriteLine("relocated test passed");
''')
f.put('input.txt', 'declared input')
f.put('BUILD.bazel', '''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_test")
msbuild_test(name="test",project="Test.csproj",target_framework="net10.0",srcs=["Program.cs"],data_paths={"input.txt":"tests/input.txt"},test_working_directory="tests",test_output_dirs=["tests/output"],linux_worker=True,allow_remote_execution=True)
''')
try:
    f.run('cold', ['//:test'], [('MSBuildAssembly', '//:test')], cold=True, tests=['//:test'])
    result = f.workspace / 'bazel-testlogs/test/test.outputs/files/tests/output/result.txt'
    assert result.read_text() == 'retained output'
    assert (f.workspace / 'input.txt').read_text() == 'declared input'
    f.run('noop', ['//:test'], [], tests=[])
finally:
    f.shutdown()
