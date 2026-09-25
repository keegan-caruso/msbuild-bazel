"""Explicit generation declarations for the pinned desktop graph (fixture only)."""
import ast
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def configure(prepared):
    root = prepared / 'bazel/upstream'
    build = root / 'BUILD.bazel'
    rows = json.loads((prepared / 'inventory.json').read_text())
    generated = []
    by_project = {}
    declarations = []
    for row in rows:
        project = row['project']
        if project in by_project:
            continue
        items = ET.parse(prepared / 'source' / project).findall('.//MicroComIdl')
        if not items:
            continue
        by_project[project] = []
        for item in items:
            parent = Path(project).parent
            source = (parent / item.get('Include').replace('\\', '/')).as_posix()
            output = (parent / item.get('CSharpInteropPath').replace('\\', '/')).as_posix()
            name = 'desktop_idl_' + str(len(generated))
            filename = Path(output).name
            declarations += [
                'msbuild_items(name=' + json.dumps(name + '_input') + ',item_type="MicroComIdl",srcs=[' + json.dumps(source) + '])',
                'msbuild_generate(name=' + json.dumps(name) + ',project="DesktopGenerate.csproj",target_framework="net10.0",build_deps=[":archive_microcom.codegenerator.msbuild_0.11.0"],package_private_assets={"MicroCom.CodeGenerator.MSBuild":"all"},items=[' + json.dumps(':' + name + '_input') + '],adapter_imports=["desktop-generate.targets"],targets=["GenerateMicroComItems"],outputs=[' + json.dumps(filename) + '],output_properties={"GeneratedSource":' + json.dumps(filename) + '},linux_worker=True,allow_remote_execution=True)',
            ]
            by_project[project].append((output, ':' + name))
            generated.append(dict(label=name, output=output, filename=filename))
            # Raw generation output must never leak into Bazel's source inputs.
            (root / output).unlink()
    if not generated:
        return
    (root / 'DesktopGenerate.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="MicroCom.CodeGenerator.MSBuild" Version="0.11.0" PrivateAssets="all" /></ItemGroup></Project>')
    (root / 'desktop-generate.targets').write_text('<Project><Target Name="BindGeneratedFile" BeforeTargets="GenerateMicroComItems"><ItemGroup><MicroComIdl Update="@(MicroComIdl)"><CSharpInteropPath>$(GeneratedSource)</CSharpInteropPath></MicroComIdl></ItemGroup></Target></Project>')
    (root / 'desktop-consume.targets').write_text('<Project><Target Name="GenerateMicroComItems" /><Target Name="UpdateMicroComCompileItems" /></Project>')
    lines = []
    for line in build.read_text().splitlines():
        if line.startswith(('msbuild_library(', 'msbuild_binary(')):
            call = ast.parse(line).body[0].value
            attrs = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
            if attrs['project'] in by_project:
                for output, label in by_project[attrs['project']]:
                    assert output in attrs['srcs'], (attrs['name'], output)
                    attrs['srcs'].remove(output)
                    attrs['srcs'].append(label)
                attrs['adapter_imports'] = ['desktop-consume.targets']
                line = call.func.id + '(' + ','.join(k + '=' + repr(v) for k, v in attrs.items()) + ')'
        lines.append(line)
    lines.insert(0, 'load("@rules_msbuild//msbuild:defs.bzl","msbuild_generate")')
    build.write_text('\n'.join(lines + declarations) + '\n')
    (prepared / 'expanded-generators.json').write_text(json.dumps(generated, indent=2) + '\n')
