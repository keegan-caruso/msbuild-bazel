"""Qualify same-action captured-graph reuse against content and namespace mutations."""
import argparse
import json
from pathlib import Path
import subprocess
from workload import ROOT, SDK, fixture


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    source=fixture(output/'worker','diamond',output/'packages',restore=True)
    request=dict(repository=str(ROOT),sdk=str((SDK/'sdk/10.0.400/MSBuild.dll').resolve().parents[2]),workspace=str(source),output=str(output/'discovery'),entry='N0003/N0003.csproj',body=str(source/'N0000/Value.cs'))
    path=output/'request.json';path.write_text(json.dumps(request,indent=2))
    result=subprocess.run([str(SDK/'dotnet'),str(ROOT/'tests/Preparation.Tests/bin/Release/net10.0/Preparation.Tests.dll'),'discovery-captured-control',str(path)],cwd=ROOT,capture_output=True,text=True,timeout=180)
    (output/'run.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout);assert all(report.values()),report
    (output/'report.json').write_text(json.dumps(report,indent=2));print(report,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);run(parser.parse_args().output.resolve())
