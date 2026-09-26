"""SDK-only projects for the stable worker path qualification."""
import json
import shutil


def create(root, workspace, transitive):
    def put(name, text):
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    w = workspace
    for name in ['global.json', '.bazelversion']:
        shutil.copyfile(root / name, w / name)
    put('MODULE.bazel', 'module(name="stable_worker_projects")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path=' + json.dumps(str(root)) + ')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",global_json="//:global.json",platforms=["linux-arm64"])\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
    put('BUILD.bazel', 'exports_files(["global.json"])\n')
    project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>{}</Project>'
    props = '''<Project><PropertyGroup><DefineConstants>$(DefineConstants);FIRST</DefineConstants></PropertyGroup>
    <Target Name="AssetMetadata" BeforeTargets="GetAssemblyAttributes"><ItemGroup>
    <AssemblyAttribute Include="System.Reflection.AssemblyMetadataAttribute" Condition="'@(EmbeddedResource)' != ''">
    <_Parameter1>%(EmbeddedResource.Identity)</_Parameter1><_Parameter2>%(EmbeddedResource.FullPath)</_Parameter2>
    </AssemblyAttribute></ItemGroup></Target></Project>'''
    c_code = 'public static class C { public const int Number = 1; public static int Value() => 1; }'
    b_code = '''public static class B {
    public const int Number = C.Number;
    public static int Value() => C.Value();
    public static string ImportValue() {
    #if FIRST
    return "first";
    #elif OTHER
    return "other";
    #else
    #error Missing imported constant
    #endif
    }
    }'''
    for name in ['C', 'B', 'A', 'Fan', 'Unrelated', 'Test']:
        deps = [] if name in ['C', 'Unrelated'] else ['C'] if name == 'B' else ['B'] if name in ['A', 'Fan'] else ['A']
        refs = '<ItemGroup>' + ''.join(f'<ProjectReference Include="../{dep}/{dep}.csproj" />' for dep in deps) + '</ItemGroup>'
        put(f'{name}/{name}.csproj', project.format(refs + ('<Import Project="Assets.props" />' if name == 'B' else '')))
        code = c_code if name == 'C' else b_code if name == 'B' else 'public class Unrelated {}' if name == 'Unrelated' else f'public static class {name} {{ public const int Number = B.Number; public static int Value() => B.Value(); }}'
        if name == 'Test':
            code = '''using System;
    using System.IO;
    using System.Linq;
    using System.Reflection;
    var assembly = typeof(B).Assembly;
    var resources = string.Join(",", assembly.GetManifestResourceNames().Order().Select(n => n + ":" + new StreamReader(assembly.GetManifestResourceStream(n)!).ReadToEnd()));
    var paths = string.Join(",", assembly.GetCustomAttributes<AssemblyMetadataAttribute>().Select(a => a.Value));
    Console.WriteLine("RESULT="+A.Number+"|"+A.Value()+"|"+B.ImportValue()+"|"+resources+"|"+paths);
    return A.Value() == 1 ? 0 : 1;'''
        put(f'{name}/Code.cs', code)
        rule = 'msbuild_test' if name == 'Test' else 'msbuild_library'
        extra = ',use_apphost=False' if name == 'Test' else ''
        if name in ['A', 'Fan']:
            extra += ',transitive_compile_references=' + str(transitive)
        if name == 'B':
            extra += ',msbuild_imports=["Assets.props"],items=[":assets"]'
        build = 'package(default_visibility=["//visibility:public"])\n' + f'load("@rules_msbuild//msbuild:defs.bzl","{rule}","msbuild_items")\n'
        if name == 'B':
            build += 'msbuild_items(name="assets",item_type="EmbeddedResource",srcs=glob(["*.txt"],allow_empty=True),metadata={"LogicalName":"asset"})\n'
        build += f'{rule}(name="{name}",project="{name}.csproj",srcs=["Code.cs"],target_framework="net10.0",deps={json.dumps(["//"+d for d in deps])},linux_worker=True{extra})\n'
        put(f'{name}/BUILD.bazel', build)
    put('B/Assets.props', props)
    put('B/asset.txt', 'one')
    return props, c_code, b_code
