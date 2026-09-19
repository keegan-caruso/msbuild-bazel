"""Native Bazel invalidation acceptance for project-owned structural inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from workload import ROOT, SDK, BAZEL, fixture, shutdown


def run(output, packages, repositories):
    output.mkdir(parents=True, exist_ok=False)
    worker = output/'worker'
    source = fixture(worker, 'diamond', packages, restore=True)
    project = source/'N0001/N0001.csproj'
    project.write_text(project.read_text().replace('</Project>', '<ItemGroup><EmbeddedResource Include="../Linked/probe.xml"><LogicalName>Probe.xml</LogicalName></EmbeddedResource></ItemGroup><ItemGroup><EmbeddedResource Include="../Added/*.xml"><LogicalName>Extra.xml</LogicalName></EmbeddedResource></ItemGroup><Import Project="Local.props" /></Project>'))
    (source/'Linked').mkdir()
    resource = source/'Linked/probe.xml'; resource.write_text('<probe>before</probe>')
    local = source/'N0001/Local.props'; local.write_text('<Project><PropertyGroup><DefineConstants>LOCAL_ONE</DefineConstants></PropertyGroup></Project>')
    layout = output/'layout.json'
    cases = []
    def invoke(label, expected):
        request = dict(schemaVersion=1, repository=str(ROOT), sdkRoot=str(SDK), bazel=str(BAZEL), workspace=str(source), state=str(worker/'state'), output=str(output/label), entry='N0003/N0003.csproj', operation='build', **{'nuget-packages':str(packages), 'project-actions':True, 'direct-checkout':True, 'bazel-repository-cache':str(repositories)})
        if layout.exists(): request['project-layout'] = str(layout)
        path=output/(label+'-request.json');path.write_text(json.dumps(request))
        with (output/(label+'.log')).open('w') as log:
            result=subprocess.run([str(SDK/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),'owned-workflow','--request',str(path)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=900)
        report=json.loads((output/label/'report.json').read_text())
        assert result.returncode==0 and report['accepted'], label
        executions=[json.loads(line) for line in (output/label/'execution.json').read_text().splitlines() if line]
        compiled=sorted(item['targetLabel'] for item in executions if item['mnemonic']=='MsbuildCompileProject' and not item.get('cacheHit',False))
        cases.append(dict(case=label,seconds=report['seconds'],compiles=report['compiles'],bindings=report['MsbuildBindProject']['executed'],discovery=report['MsbuildDiscover']['executed'],targets=compiled))
        (output/'report.json').write_text(json.dumps(cases,indent=2))
        print(label,report['compiles'],round(report['seconds'],3),flush=True)
        if expected is not None: assert report['compiles']==expected, cases[-1]
        if label in ['linked-resource','local-import','shared-import','noop']:
            assert report['MsbuildBindProject']['executed']==(1 if label=='linked-resource' else expected), cases[-1]
        if label=='linked-resource': assert report['MsbuildDiscover']['executed']==0, cases[-1]
        if label in ['linked-resource','local-import']:
            expected_targets=sorted('//:project_'+hashlib.sha256(f'N{i:04}/N{i:04}.csproj'.encode()).hexdigest() for i in ([1] if label=='linked-resource' else [1,3]))
            assert compiled==expected_targets, compiled
            assembly=worker/'state/g/bazel-bin/build.bundle/app/N0001.dll'
            assert b'<probe>after</probe>' in assembly.read_bytes(), 'Updated resource missing from compiled output'
        return report
    try:
        invoke('producer',4)
        layout.write_bytes((output/'producer/project-layout.json').read_bytes())
        # Establish the same generated declaration before mutation comparisons.
        invoke('declared',0)
        resource.write_text('<probe>after</probe>')
        invoke('linked-resource',1)
        # Membership changes must still rerun discovery and refresh the local layout.
        layout.unlink()
        added=source/'Added/extra.xml';added.parent.mkdir();added.write_text('<extra>added resource</extra>')
        report=invoke('resource-added',None)
        assert report['MsbuildDiscover']['executed']>=1 and report['compiles']<=2
        assembly=worker/'state/g/bazel-bin/build.bundle/app/N0001.dll'
        assert b'<extra>added resource</extra>' in assembly.read_bytes()
        added.unlink()
        report=invoke('resource-removed',None)
        assert report['MsbuildDiscover']['executed']>=1 and report['compiles']<=2
        assert b'<extra>added resource</extra>' not in assembly.read_bytes()
        layout.write_bytes((output/'resource-removed/project-layout.json').read_bytes())
        local.write_text(local.read_text().replace('LOCAL_ONE','LOCAL_TWO'))
        invoke('local-import',2)
        props=source/'Directory.Build.props'
        props.write_text(props.read_text().replace('</Project>','<PropertyGroup><DefineConstants>SHARED</DefineConstants></PropertyGroup></Project>'))
        invoke('shared-import',4)
        invoke('noop',0)
    finally:
        shutdown(worker)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--packages',type=Path,required=True);parser.add_argument('--repositories',type=Path,required=True)
    args=parser.parse_args();run(args.output.resolve(),args.packages.resolve(),args.repositories.resolve())
