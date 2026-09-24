"""Compile a tiny consumer against the source-built framework/reference closure."""
from pathlib import Path
import sys

workspace=Path(sys.argv[1]).resolve()
smoke=workspace/'smoke';smoke.mkdir()
implementation='src_libraries_System.Collections.Immutable_src_System.Collections.Immutable_net10.0'
(smoke/'Smoke.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../upstream/src/libraries/System.Collections.Immutable/src/System.Collections.Immutable.csproj" /></ItemGroup></Project>')
(smoke/'runtimeconfig.template.json').write_text('{"framework":{"name":"Microsoft.NETCore.App","version":"10.0.11"}}')
(smoke/'Program.cs').write_text('''using System.Collections.Immutable;
var values = ImmutableArray.Create(1, 2, 3);
var dictionary = ImmutableDictionary<string, int>.Empty.Add("answer", 42);
return values.Length == 3 && dictionary["answer"] == 42 ? 0 : 1;
''')
build=workspace/'upstream/BUILD.bazel'
s=build.read_text().replace('name="'+implementation+'_paired",','name="'+implementation+'_paired",visibility=["//smoke:__pkg__"],')
build.write_text(s)
(smoke/'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_test", "msbuild_reference_pack")
msbuild_reference_pack(name="framework",assemblies=["//upstream:IMPL_paired"])
msbuild_test(name="smoke",project="Smoke.csproj",assembly_name="Smoke",srcs=["Program.cs"],msbuild_imports=["runtimeconfig.template.json"],target_framework="net10.0",deps=["//upstream:IMPL_paired"],reference_pack=":framework",runtime_host="//runtime:host",use_apphost=False,linux_worker=True,size="small")
'''.replace('IMPL',implementation))
