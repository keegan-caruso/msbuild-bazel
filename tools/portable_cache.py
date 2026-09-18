"""Explicit snapshot broker for the owned package-free native-cache slice."""
import concurrent.futures
import hashlib
import io
import json
import platform
from pathlib import Path, PurePosixPath
import shutil
from urllib.request import Request, urlopen
import zipfile

from preparation_identity import digest, tree_snapshot
from native_qualification import qualify

POLICY = 'owned-net10-release-env-v1'

def sha(data): return hashlib.sha256(data).hexdigest()

def environment(sdk, home, temp, workspace):
    return dict(PATH='/usr/bin:/bin',LANG='en_US.UTF-8',HOME=str(home),DOTNET_ROOT=str(sdk),DOTNET_HOST_PATH=str(sdk/'dotnet'),DOTNET_CLI_HOME=str(home),NUGET_PACKAGES=str(workspace/'.nuget/packages'),DOTNET_NOLOGO='1',DOTNET_CLI_TELEMETRY_OPTOUT='1',DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1',MSBUILDDISABLENODEREUSE='1',TMPDIR=str(temp),TMP=str(temp),TEMP=str(temp))

def capture(source, home, sdk):
    projects=qualify(source);before=tree_snapshot(source,[source]);authored={};restore={}
    for p in source.rglob('*'):
        if not p.is_file():continue
        relative=p.relative_to(source).as_posix();data=p.read_bytes()
        if 'obj' in p.relative_to(source).parts:
            # Build consumes assets plus generated NuGet props/targets; restore's
            # path-salted diagnostic/cache receipts are not Build inputs.
            if p.name!='project.assets.json' and not p.name.endswith(('.nuget.g.props','.nuget.g.targets')):continue
            restore[relative]=data.decode().replace(str(source),'${WORKSPACE}').replace(str(sdk),'${SDK}').replace(str(home),'${HOME}')
        else:authored[relative]=data
    if before!=tree_snapshot(source,[source]):raise ValueError('source changed during capture')
    for project in projects:
        prefix=str(Path(project).parent)+'/obj/'
        required={prefix+'project.assets.json',prefix+Path(project).name+'.nuget.g.props',prefix+Path(project).name+'.nuget.g.targets'}
        if not required.issubset(restore):raise ValueError('incomplete restored build inputs')
    shared=digest({p:sha(b) for p,b in authored.items() if not p.endswith('.cs')})
    nodes={}
    for project,deps in projects.items():
        prefix=str(Path(project).parent)+'/'
        inputs={p:sha(b) for p,b in authored.items() if p.startswith(prefix)}
        inputs.update({p:sha(text.encode()) for p,text in restore.items() if p.startswith(prefix)})
        nodes[project]=dict(identity=digest(dict(shared=shared,inputs=inputs)),dependencies=deps)
    return authored,restore,nodes

def tool_identity(sdk_identity, runner_files, controller_files, imports):
    # Roles identify verified tools; their installation directories are not inputs.
    return digest(dict(policy=POLICY,platform=dict(system=platform.system(),machine=platform.machine()),sdk=sdk_identity,runner={p.name:sha(p.read_bytes()) for p in runner_files},controller={p.name:sha(p.read_bytes()) for p in controller_files},imports={p.name:sha(p.read_bytes()) for p in imports}))

def valid_path(name):
    return isinstance(name,str) and bool(name) and not name.startswith('/') and '\\' not in name and all(part not in ('','.','..') for part in name.split('/'))

def validate_bundle(files):
    seal=json.loads(files['bundle.json']);results=json.loads(files['results.json']);artifacts=json.loads(files['artifacts.json'])
    if not isinstance(seal,dict) or not isinstance(results,dict) or not isinstance(artifacts,list) or any(not isinstance(item,dict) for item in artifacts):raise ValueError('invalid bundle metadata shape')
    if seal.get('schemaVersion')!=1 or seal.get('resultsSha256')!=sha(files['results.json']) or seal.get('artifactsSha256')!=sha(files['artifacts.json']):raise ValueError('invalid seal')
    if not artifacts:raise ValueError('empty artifacts')
    expected={'bundle.json','results.json','artifacts.json'}
    for item in artifacts:
        p=item['path']
        if not valid_path(p) or 'artifacts/'+p in expected:raise ValueError('invalid artifact path')
        data=files['artifacts/'+p]
        if len(data)!=item['size'] or sha(data)!=item['sha256']:raise ValueError('invalid artifact bytes')
        expected.add('artifacts/'+p)
    if set(files)!=expected:raise ValueError('undeclared bundle members')
    if not isinstance(results.get('key'),str) or len(results['key'])!=64 or any(c not in '0123456789abcdef' for c in results['key']):raise ValueError('invalid project key')
    return results

def unpack(data):
    files={};total=0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for item in archive.infolist():
            total+=item.file_size
            if total>64*1024*1024 or not valid_path(item.filename) or item.filename in files or (item.external_attr>>16)&0xf000==0xa000:raise ValueError('invalid archive member')
            files[item.filename]=archive.read(item)
    validate_bundle(files)
    return files

def pack(folder):
    files={p.relative_to(folder).as_posix():p.read_bytes() for p in folder.rglob('*') if p.is_file()}
    results=validate_bundle(files);buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as z:
        for name,data in sorted(files.items()):
            item=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));item.compress_type=zipfile.ZIP_DEFLATED;z.writestr(item,data)
    return results,buffer.getvalue()

def fetch(url):
    with urlopen(url,timeout=5) as response:return response.read(64*1024*1024+1)

def put(url,data):
    with urlopen(Request(url,data=data,method='PUT'),timeout=5) as response:response.read()

def seed(endpoint, catalog, manifest, destination):
    """Catalog is an explicit immutable snapshot, not an undeclared latest pointer."""
    destination.mkdir(parents=True,exist_ok=True)
    selected=[r for r in catalog if r['toolchain']==manifest['toolchain'] and manifest['projects'].get(r['project'],{}).get('identity')==r['inputs']]
    rejected=[];accepted=[];verified_blobs=[]
    def one(record):
        try:
            data=fetch(endpoint+'/cas/'+record['blob'])
            if sha(data)!=record['blob']:raise ValueError('remote blob hash mismatch')
            files=unpack(data);result=json.loads(files['results.json'])
            if any(result[k]!=record[k] for k in ('key','project','inputs','toolchain')):raise ValueError('catalog/result mismatch')
            return record,files
        except (OSError,ValueError,KeyError,zipfile.BadZipFile) as error:return record,str(error)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for record,files in pool.map(one,selected):
            if isinstance(files,str):rejected.append(dict(key=record['key'],reason=files));continue
            for relative,data in files.items():
                target=destination/record['key']/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            accepted.append(record['key']);verified_blobs.append(record['blob'])
    return dict(accepted=accepted,rejected=rejected,verifiedBlobs=verified_blobs)

def publish(endpoint, folder, *, verified_blobs=()):
    """Called only for a successful Bazel action; returns a transportable snapshot."""
    # Only receipts from successful verified downloads in this invocation qualify.
    # Comparing full output bytes still detects changed or newly compiled bundles.
    verified_blobs=frozenset(verified_blobs)
    def one(bundle):
        result,data=pack(bundle);blob=sha(data)
        try:
            if blob not in verified_blobs:put(endpoint+'/cas/'+blob,data)
        except OSError as error:return dict(error=str(error),key=result['key'])
        return dict(key=result['key'],project=result['project'],inputs=result['inputs'],toolchain=result['toolchain'],blob=blob)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        entries=list(pool.map(one,sorted(folder.iterdir())))
    return dict(entries=[e for e in entries if 'error' not in e],errors=[e for e in entries if 'error' in e])


def reset_workspace(destination, module, *, preserve_lock=True):
    """Regenerate declared inputs, retaining Bazel's lock only for identical modules."""
    lock=None
    previous=destination/'MODULE.bazel'
    receipt=destination/'MODULE.bazel.lock'
    if preserve_lock and module is not None and previous.is_file() and receipt.is_file() and previous.read_text()==module:
        lock=receipt.read_bytes()
    if destination.exists():shutil.rmtree(destination)
    destination.mkdir()
    if module is not None:(destination/'MODULE.bazel').write_text(module)
    if lock is not None:(destination/'MODULE.bazel.lock').write_bytes(lock)
