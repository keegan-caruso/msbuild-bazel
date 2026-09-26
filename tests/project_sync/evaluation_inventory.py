"""Report evaluated upstream inputs without invoking targets or accepting mappings.

Usage: evaluation_inventory.py CHECKOUT OUTPUT_JSON PROJECT.csproj [...]
Run on disposable pinned checkouts after their documented bootstrap. This is an
inspection tool: it never marks a custom item or document safe automatically.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from test_sync import DOTNET, SDK

with tempfile.TemporaryDirectory(prefix='sync-inventory-') as temporary:
    folder = Path(temporary)
    references = ''.join(f'<Reference Include="{name}" HintPath="{SDK}/{name}.dll"/>'
                         for name in ['Microsoft.Build', 'Microsoft.Build.Framework'])
    (folder/'Inventory.csproj').write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>'
        '<OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings></PropertyGroup>'
        f'<ItemGroup>{references}</ItemGroup></Project>')
    (folder/'Program.cs').write_text(Path(__file__).with_name('EvaluationInventory.cs.txt').read_text())
    subprocess.run([str(DOTNET/'dotnet'), 'build', str(folder/'Inventory.csproj'), '-c', 'Release'], check=True)
    subprocess.run([str(DOTNET/'dotnet'), str(folder/'bin/Release/net10.0/Inventory.dll'),
                    str(SDK), *sys.argv[1:]], check=True)
    for row in json.loads(Path(sys.argv[2]).read_text()):
        print(row['project'], row.get('framework', ''), row.get('error',
              f"{len(row.get('documents', []))} non-SDK documents"))
