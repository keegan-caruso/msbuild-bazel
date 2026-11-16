"""Write a pinned one-project graph contract for the qualification driver."""
import json


def write_contract(folder, sources=()):
    (folder / 'driver-contract.json').write_text(json.dumps(dict(
        Version=1, Entry='Task.csproj', SdkVersion='11.0.100',
        Properties=dict(Configuration='Release'), SharedInputs=[],
        Projects={'Task.csproj': dict(Inputs=['Task.csproj', 'NativeBuild.cs', *sources],
                                   OutputDirectories=['bin/Release/net11.0', 'obj/Release/net11.0'])}), indent=2) + '\n')
