"""Shared execution-log checks for bounded remote qualification fixtures."""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
MNEMONICS = {'MSBuildAssembly','MSBuildGenerate','MSBuildNugetExtract','MSBuildRunnerBootstrap','DotnetSdkRuntime','TestRunner'}

class RemoteFixture:
    def __init__(self, directory, executor, workspace=None, *, instance="rules-msbuild-remote-inputs"):
        self.folder=Path(directory).resolve();self.folder.mkdir(parents=True,exist_ok=False)
        self.workspace=Path(workspace).resolve() if workspace else self.folder/'source'
        self.workspace.mkdir(exist_ok=True)
        self.bazel=os.environ['RULES_MSBUILD_BAZEL'];self.executor=executor;self.rows=[]
        self.base=self.folder/'base';self.instance=instance
        self.version=subprocess.check_output([self.bazel,'--version'],text=True).strip()
        assert self.version in ['bazel 8.8.0','bazel 9.2.0']

    def put(self,name,text):
        p=self.workspace/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)

    def sdk(self):
        self.put('MODULE.bazel',f'''module(name="remote_fixture")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})
dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")
dotnet.sdk(name="dotnet",version="10.0.400",platforms=["linux-arm64"])
use_repo(dotnet,"dotnet")
register_toolchains("@dotnet//:all")
''')

    def run(self,case,targets,expected,*,command='test',cold=False,error=None,tests=None,downloads="all",extra_args=()):
        execution=self.folder/(case+'.execution.json')
        cmd=[self.bazel,'--output_base='+str(self.base),'--ignore_all_rc_files',command,*targets,'--jobs=2','--lockfile_mode=off','--incompatible_strict_action_env','--disk_cache=','--remote_executor='+self.executor,'--remote_cache='+self.executor,'--remote_instance_name='+self.instance,'--noremote_local_fallback','--spawn_strategy=remote','--remote_accept_cached='+str(not cold).lower(),'--remote_upload_local_results=false','--remote_download_outputs='+downloads,'--remote_default_exec_properties=ISA=aarch64','--remote_default_exec_properties=OSFamily=linux','--remote_default_exec_properties=rules_msbuild_image=47a9e2fed018-sdk-removed','--execution_log_json_file='+str(execution)]
        assert downloads in ['all','toplevel','minimal'], downloads
        cmd+=list(extra_args)
        if command=='test':cmd+=['--test_output=errors']
        start=time.perf_counter()
        result=subprocess.run(cmd,cwd=self.workspace,text=True,capture_output=True,timeout=900)
        output=result.stdout+result.stderr;(self.folder/(case+'.log')).write_text(output)
        assert (result.returncode!=0)==bool(error),(case,output[-6000:])
        if error:assert error in output,(case,output[-6000:])
        data=execution.read_text().strip();actions=[];decoder=json.JSONDecoder()
        while data:
            action,end=decoder.raw_decode(data);data=data[end:].lstrip()
            if action.get('mnemonic') in MNEMONICS:actions.append(action)
        assert all(x.get('runner') in ['remote','remote cache hit'] for x in actions),actions
        if cold:assert all(not x.get('cacheHit') for x in actions),actions
        executed=sorted((x['mnemonic'],x['targetLabel']) for x in actions if not x.get('cacheHit') and x['mnemonic'] in ['MSBuildAssembly','MSBuildGenerate'])
        assert executed==sorted(expected),(case,executed)
        ran_tests=sorted({x['targetLabel'] for x in actions if x['mnemonic']=='TestRunner' and not x.get('cacheHit')})
        if tests is not None:assert ran_tests==tests,(case,ran_tests)
        record=dict(case=case,seconds=time.perf_counter()-start,executed=executed,tests=ran_tests,actions=[{k:x.get(k) for k in ['mnemonic','targetLabel','runner','cacheHit','exitCode']} for x in actions])
        self.rows.append(record);(self.folder/'report.json').write_text(json.dumps(dict(bazel=self.version,cases=self.rows),indent=2)+'\n');print(json.dumps(record),flush=True)
        return actions

    def shutdown(self):
        subprocess.run([self.bazel,'--output_base='+str(self.base),'shutdown'],cwd=self.workspace,check=True)
