import json,os,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parent
for p in ['storage-ac/persistent_state','storage-cas/persistent_state','storage-fsac/persistent_state','worker/build','worker/cache','worker/cas/persistent_state']:(root/p).mkdir(parents=True,exist_ok=True)
processes={}
for case,binary in [('storage','bb_storage'),('frontend','bb_storage'),('scheduler','bb_scheduler'),('worker','bb_worker'),('runner','bb_runner')]:
 with (root/(case+'.log')).open('w') as log:
  p=subprocess.Popen([root/'bin'/binary,root/(case+'.jsonnet')],cwd=root,env=dict(os.environ,PWD=str(root),OS='Linux'),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 processes[case]=p
(root/'pids.json').write_text(json.dumps({k:p.pid for k,p in processes.items()}))
time.sleep(2)
for k,p in processes.items():print(k,p.pid,p.poll(),(root/(k+'.log')).read_text()[-600:])
assert all(p.poll() is None for p in processes.values())
