"""Windows ZIP selection and SDK layout staging on the portable Bazel host.

The fixture dotnet.exe is inert; these tests never execute a Windows binary.
Native Windows compilation and isolation are separate qualification gates.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BAZEL = os.environ.get('RULES_MSBUILD_BAZEL', str(ROOT / 'scripts/bazel-launcher.sh'))


class WindowsArchives(unittest.TestCase):
    def invoke(self, folder, command, *arguments, success=True):
        completed = subprocess.run(
            [BAZEL, '--batch', '--output_base=' + str(folder / 'base'), '--ignore_all_rc_files',
             command, *arguments, '--lockfile_mode=update'],
            cwd=folder, text=True, capture_output=True, timeout=180)
        output = completed.stdout + completed.stderr
        self.assertEqual(completed.returncode == 0, success, output)
        return output

    def archive(self, folder, name, files):
        path = folder / (name + '.zip')
        with zipfile.ZipFile(path, 'w') as archive:
            for member, data in files.items():
                entry = zipfile.ZipInfo(member)
                entry.external_attr = 0o100755 << 16
                archive.writestr(entry, data)
        digest = hashlib.sha512(path.read_bytes()).digest()
        return {'rid': 'win-x64', 'name': name, 'url': path.as_uri(), 'hash': digest.hex()}, digest

    def module(self, folder, declaration):
        (folder / 'MODULE.bazel').write_text(
            'bazel_dep(name="platforms",version="1.0.0")\n'
            'bazel_dep(name="rules_msbuild",version="0.0.0")\n'
            'local_path_override(module_name="rules_msbuild",path=' + json.dumps(str(ROOT)) + ')\n'
            'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n' +
            declaration + '\nuse_repo(dotnet,"downloaded")\n')
        (folder / 'BUILD.bazel').write_text('')

    def test_opt_in_sdk_zip_stages_exe_and_long_spaced_file_list(self):
        with tempfile.TemporaryDirectory(prefix='windows-sdk-') as temporary:
            folder = Path(temporary)
            files = {'dotnet.exe': b'inert Windows executable', 'sdk/11.0.100/dotnet.dll': b'sdk',
                     'host/fxr/11.0.0/hostfxr.dll': b'fxr',
                     'shared/Microsoft.NETCore.App/11.0.0/coreclr.dll': b'runtime'}
            # Exceeds the Windows command-line bound without a response file.
            files.update({'sdk/11.0.100/space directory/' + str(i) + '-reference-name.dll': b'payload'
                          for i in range(600)})
            archive, _ = self.archive(folder, 'sdk', files)
            archive['name'] = 'dotnet-sdk-win-x64.zip'
            installer = dict(archive, name='dotnet-sdk-win-x64.exe', url='https://example.invalid/installer.exe')
            metadata = {'releases': [{'sdk': {'version': '11.0.100', 'runtime-version': '11.0.0',
                                             'files': [installer, archive]}}]}
            (folder / 'releases.json').write_text(json.dumps(metadata))
            self.module(folder, 'dotnet.sdk(name="downloaded",version="11.0.100",platforms=["win-x64"],metadata_urls=[' +
                        json.dumps((folder / 'releases.json').as_uri()) + '])')
            (folder / 'inspect.bzl').write_text('''load("@rules_msbuild//msbuild:defs.bzl", "MSBuildRuntimeInfo")
def _inspect(ctx):
    runtime = ctx.attr.host[MSBuildRuntimeInfo]
    output = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.write(output, json.encode({"entry_point": runtime.entry_point, "rid": runtime.runtime_identifier, "tree": runtime.directory.path}))
    return [DefaultInfo(files = depset([output], transitive = [runtime.files]))]
inspect = rule(implementation = _inspect, attrs = {"host": attr.label()})
''')
            (folder / 'BUILD.bazel').write_text('''load(":inspect.bzl", "inspect")
platform(name="windows",constraint_values=["@platforms//os:windows","@platforms//cpu:x86_64"])
inspect(name="inspect",host="@downloaded//:sdk_host")
''')
            output = self.invoke(folder, 'build', '//:inspect', '@downloaded//:dotnet', '--platforms=//:windows')
            self.assertIn('Build completed successfully', output)
            info = json.loads((folder / 'bazel-bin/inspect.json').read_text())
            self.assertEqual((info['entry_point'], info['rid']), ('dotnet.exe', 'win-x64'))
            tree = folder / 'base/execroot/_main' / info['tree']
            for name, data in files.items():
                self.assertEqual((tree / name).read_bytes(), data, name)
            # Existing native lockfile fact names and archive schema are unchanged.
            lock = (folder / 'MODULE.bazel.lock').read_text()
            self.assertIn('sdk-v1', lock)
            self.assertIn('win-x64', lock)
            self.assertNotIn('linux-arm64', lock)

    def test_custom_sdk_zip_requires_exe_layout(self):
        with tempfile.TemporaryDirectory(prefix='windows-sdk-layout-') as temporary:
            folder = Path(temporary)
            archive, digest = self.archive(folder, 'sdk', {'dotnet': b'wrong host name',
                'sdk/11.0.100/version.txt': b'sdk', 'shared/Microsoft.NETCore.App/11.0.0/version.txt': b'runtime'})
            integrity = 'sha512-' + base64.b64encode(digest).decode()
            self.module(folder, 'dotnet.sdk_archive(name="downloaded",version="11.0.100",runtime_version="11.0.0",'
                        'platform="win-x64",urls=[' + json.dumps(archive['url']) + '],integrity=' + json.dumps(integrity) + ')')
            output = self.invoke(folder, 'query', 'deps(@downloaded//:files)', success=False)
            self.assertIn('SDK archive is missing declared layout component: dotnet.exe', output)

    def test_coreclr_and_aspnet_zip_metadata(self):
        for kind in ['coreclr', 'aspnetcore']:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix='windows-runtime-') as temporary:
                folder = Path(temporary)
                files = {'dotnet.exe': b'host', 'shared/Microsoft.NETCore.App/11.0.0/coreclr.dll': b'coreclr'}
                if kind == 'aspnetcore':
                    files['shared/Microsoft.AspNetCore.App/11.0.0/Microsoft.AspNetCore.App.deps.json'] = b'{}'
                archive, _ = self.archive(folder, 'runtime', files)
                prefix = 'aspnetcore' if kind == 'aspnetcore' else 'dotnet'
                archive['name'] = prefix + '-runtime-win-x64.zip'
                distracting = dict(archive, name='aspnetcore-runtime-composite-win-x64.zip' if kind == 'aspnetcore' else 'dotnet-apphost-pack-win-x64.zip',
                                   url='https://example.invalid/other.zip')
                component = 'aspnetcore-runtime' if kind == 'aspnetcore' else 'runtime'
                (folder / 'releases.json').write_text(json.dumps({'releases': [{component: {
                    'version': '11.0.0', 'files': [distracting, archive]}}]}))
                self.module(folder, 'dotnet.runtime(name="downloaded",version="11.0.0",kind=' + json.dumps(kind) +
                            ',platforms=["win-x64"],metadata_urls=[' + json.dumps((folder / 'releases.json').as_uri()) + '])')
                output = self.invoke(folder, 'query', 'kind("msbuild_runtime", deps(@downloaded//:runtime))', '--output=build')
                self.assertIn('entry_point = "dotnet.exe"', output)
                self.assertIn('runtime_identifier = "win-x64"', output)


if __name__ == '__main__':
    unittest.main()
