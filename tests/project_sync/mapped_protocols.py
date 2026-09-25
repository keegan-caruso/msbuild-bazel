"""Migrate the existing MTP fixture setup to explicit sync mappings."""
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tests/explicit_msbuild'))
from protocol import setup, command, BAZEL

folder=Path(sys.argv[1]).resolve()
workspace=setup(folder)
(workspace/'Mtp/BUILD.bazel').unlink()
(workspace/'MODULE.bazel').write_text('module(name="mapped_mtp")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(ROOT))+')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",version="10.0.400")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
mappings=dict(packages={
    'xunit.v3.mtp-v2/4.0.0':dict(label='//packages:xunit.v3.mtp-v2',roles=['deps','build_deps'],analyzers=['//packages:xunit.analyzers']),
    'Microsoft.Testing.Extensions.TrxReport/2.3.3':dict(label='//packages:microsoft.testing.extensions.trxreport',roles=['deps','build_deps']),
},tests={'Mtp/Mtp.csproj':dict(protocol='mtp',outputDirectories=['logs'],filterArgument='--filter-query')})
(workspace/'sync.json').write_text(json.dumps(mappings))
authored='load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\nmsbuild_sync(name="sync",projects=["Mtp/Mtp.csproj"],mappings="sync.json")\n'
(workspace/'BUILD.bazel').write_text(authored)
startup=[BAZEL,'--output_base='+str(folder/'base')]
rows=[]
try:
    p=command(startup+['run','//:sync'],workspace,folder/'sync.log')
    assert p.returncode==0,(p.stdout+p.stderr)[-5000:]
    (workspace/'BUILD.bazel').write_text('load(":projects.generated.bzl","app_projects")\n'+authored+'app_projects()\n')
    for name,flags,success in [('pass',[],True),('failure',['--test_env=CASE=fail'],False),('restore',[],True)]:
        p=command(startup+['test','//:Mtp_Mtp_net10_0','--test_output=errors',*flags],workspace,folder/(name+'.log'))
        assert (p.returncode==0)==success,(name,(p.stdout+p.stderr)[-5000:])
        xml=ET.parse(workspace/'bazel-testlogs/Mtp_Mtp_net10_0/test.xml').getroot()
        row=dict(case=name,tests=len(xml.findall('.//testcase')),failures=len(xml.findall('.//failure')),skipped=len(xml.findall('.//skipped')))
        assert row==dict(case=name,tests=4,failures=0 if success else 1,skipped=1),row
        rows.append(row)
    (folder/'report.json').write_text(json.dumps(rows,indent=2)+'\n')
finally:
    subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
print('Mapped MTP pass/failure/restoration controls passed')
