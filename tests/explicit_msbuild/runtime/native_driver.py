"""Write a pinned one-project graph contract for the qualification driver."""
import json


def write_contract(folder):
    (folder / 'driver-contract.json').write_text(json.dumps(dict(
        Version=1, Entry='Task.csproj', SdkVersion='10.0.400',
        Properties=dict(Configuration='Release'), SharedInputs=[],
        Projects={'Task.csproj': dict(Inputs=['Task.csproj', 'NativeBuild.cs'],
                                   OutputDirectories=['bin/Release/net10.0', 'obj/Release/net10.0'])}), indent=2) + '\n')
