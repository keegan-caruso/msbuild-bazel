"""Add an entirely Bazel-built consumer of the authored Primitives contract."""
from pathlib import Path
import re
import sys

root=Path(sys.argv[1])/'upstream'
# Outside the upstream project tree's imports: this is an ordinary SDK consumer.
workspace=root.parent
smoke=workspace/'smoke';smoke.mkdir(exist_ok=True)
(smoke/'Smoke.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../upstream/src/libraries/Microsoft.Extensions.Primitives/src/Microsoft.Extensions.Primitives.csproj" /></ItemGroup></Project>')
(smoke/'Program.cs').write_text('''using System;
using System.IO;
using Microsoft.Extensions.Primitives;
var values = StringValues.Concat(new StringValues("a"), new StringValues("b"));
if (values.Count != 2 || values[1] != "b") return 1;
if (!new StringSegment("prefix-value", 7, 5).Equals(new StringSegment("value"))) return 2;
Console.WriteLine(typeof(StringValues).Assembly.FullName);
Console.WriteLine(Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(typeof(StringValues).Assembly.Location))));
return 0;
''')
build=root/'BUILD.bazel'
s=build.read_text().replace('name="src_libraries_Microsoft.Extensions.Primitives_src_Microsoft.Extensions.Primitives_net10.0_paired",','name="src_libraries_Microsoft.Extensions.Primitives_src_Microsoft.Extensions.Primitives_net10.0_paired",visibility=["//visibility:public"],')
s=re.sub(r'(visibility=\["//visibility:public"\],)+', 'visibility=["//visibility:public"],', s)
build.write_text(s)
(smoke/'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_test")
msbuild_test(name="smoke",project="Smoke.csproj",assembly_name="Smoke",target_framework="net10.0",test_protocol="executable",test_output_type="exe",srcs=["Program.cs"],deps=["//upstream:src_libraries_Microsoft.Extensions.Primitives_src_Microsoft.Extensions.Primitives_net10.0_paired"],runtime_host="//runtime:host",linux_worker=True,size="small")
''')
