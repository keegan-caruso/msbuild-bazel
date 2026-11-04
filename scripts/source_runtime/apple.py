"""One owned Apple Container for the source-runtime developer workflow."""
import fcntl
import importlib.util
import json
import platform
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import uuid

from .common import ROOT, acquire, digest, read_recipe, run, save


def demo_helpers():
    spec = importlib.util.spec_from_file_location('runtime_demo_control', ROOT/'scripts/setup-runtime-demo.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def operate(args, application):
    base = args.output.expanduser().resolve()
    with (base/'setup.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state = json.loads((base/'setup.json').read_text())
        if state.get('kind') != 'apple-source-runtime':
            raise ValueError('Output belongs to another workflow')
        if not state.get('ready'):
            raise ValueError('Complete setup with --resume before running the app')
        helpers = demo_helpers()
        worker = helpers.inspect(state['worker'])
        if not worker or worker['configuration']['labels'].get('rules-msbuild.source-runtime') != state['id']:
            raise ValueError('Source-runtime worker is missing or has different ownership')
        if worker['configuration']['image']['descriptor']['digest'] != state['image'].split('@',1)[1]:
            raise ValueError('Source-runtime worker image differs from setup')
        if worker['status']['state'] != 'running':
            run(['container','start',state['worker']])
        command = ['container','exec',state['worker'],'python3','/source-runtime/rules/scripts/setup-source-runtime.py',
                   '/source-runtime/work','--test' if args.test else '--run',*(['--',*application] if application else [])]
        return subprocess.run(command).returncode


def setup(args):
    if platform.machine() != 'arm64' or not shutil.which('container'):
        raise ValueError('Apple silicon and Apple Container are required')
    if args.native_toolchain or args.sandbox or args.registry or args.repository_cache or args.host_space_path:
        raise ValueError('Native tool/cache paths are Linux options; Apple setup creates its own declared environment')
    base = args.output.expanduser().resolve()
    helpers = demo_helpers()
    if args.resume:
        state = json.loads((base/'setup.json').read_text())
        if state.get('kind') != 'apple-source-runtime':
            raise ValueError('Output belongs to another workflow')
        for supplied,recorded in [(args.image,state['requestedImage']),(args.cache_url,state['cacheUrl'])]:
            if supplied is not None and supplied != recorded:
                raise ValueError('Setup options changed; use a fresh directory')
        args.image=state['requestedImage']
        if digest(base/'rules.tar') != state['rulesSha256']:
            raise ValueError('Frozen source-runtime rules changed')
    else:
        if base.exists():
            raise ValueError('Use a fresh output directory or --resume')
        parent=base.parent
        while not parent.exists():parent=parent.parent
        if shutil.disk_usage(parent).free < 32*1024**3:
            raise ValueError('A new source-runtime worker needs 32 GiB free')
        if args.image and not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}',args.image):
            raise ValueError('Use an immutable image reference')
        base.mkdir(parents=True,mode=0o700)
        identifier = uuid.uuid4().hex[:10]
        archive = base/'rules.tar'
        state = dict(version=1,kind='apple-source-runtime',id=identifier,worker='msbuild-source-runtime-'+identifier,
                     requestedImage=args.image,cacheUrl=args.cache_url,rulesSha256=helpers.snapshot(archive),ready=False)
        save(base/'setup.json',state)
    with (base/'setup.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Keep the host entry point runnable after moving/deleting the original checkout.
        frozen=base/'rules'
        if not frozen.exists():
            with tarfile.open(base/'rules.tar') as archive:
                for member in archive:
                    path=Path(member.name)
                    if not member.isfile() or path.is_absolute() or '..' in path.parts:
                        raise ValueError('Frozen rules contain an invalid member')
                    destination=frozen/path
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    destination.write_bytes(archive.extractfile(member).read())
                    destination.chmod(member.mode)
        if 'image' not in state:
            if args.image:
                state['image']=args.image
            else:
                context=base/'image';context.mkdir(exist_ok=True)
                shutil.copyfile(frozen/'containers/runtime-demo.Dockerfile',context/'Dockerfile')
                tag='rules-msbuild-source-runtime:'+state['id']
                print('Source runtime: build native environment',flush=True)
                with (base/'image.log').open('w') as log:
                    run(['container','build','--platform','linux/arm64','--cpus','4','--memory','4G','--tag',tag,context],stdout=log,stderr=subprocess.STDOUT)
                image=json.loads(subprocess.check_output(['container','image','inspect',tag],text=True))[0]['configuration']
                state['image']=image['name'].rsplit(':',1)[0]+'@'+image['descriptor']['digest']
                run(['container','image','tag',tag,state['image']])
            save(base/'setup.json',state)
        worker=helpers.inspect(state['worker'])
        if worker:
            if worker['configuration']['labels'].get('rules-msbuild.source-runtime') != state['id']:
                raise ValueError('Container ownership differs')
            if worker['configuration']['image']['descriptor']['digest'] != state['image'].split('@',1)[1]:
                raise ValueError('Container image differs')
            if worker['status']['state']!='running':run(['container','start',state['worker']])
        else:
            run(['container','run','-d','--init','--arch','arm64','--name',state['worker'],'--cpus','4','--memory','8G',
                 '--cap-add','SYS_ADMIN','--masked-path','NONE','--read-only-path','NONE',
                 '--label','rules-msbuild.source-runtime='+state['id'],'--volume',str(base)+':/host:ro',state['image'],'sleep','infinity'])
        run(['container','exec',state['worker'],'mkdir','-p','/source-runtime/rules'])
        run(['container','exec',state['worker'],'tar','-xf','/host/rules.tar','-C','/source-runtime/rules'])
        command=['container','exec',state['worker'],'python3','/source-runtime/rules/scripts/setup-source-runtime.py',
                 '/source-runtime/work','--host-space-path=/host']
        if state['cacheUrl']:command+=['--cache-url='+state['cacheUrl']]
        if args.source_archive:
            source=read_recipe()['source']
            acquire(base/'runtime-source.tar.gz',source['url'],source['sha256'],args.source_archive.resolve())
            state['suppliedSource']=True
            save(base/'setup.json',state)
        if state.get('suppliedSource'):command+=['--source-archive=/host/runtime-source.tar.gz']
        if args.resume:command+=['--resume']
        print('Source runtime: prepare, build and verify the app (log: '+str(base/'setup.log')+')',flush=True)
        with (base/'setup.log').open('a') as log:
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            for line in process.stdout:
                log.write(line);log.flush()
                if line.startswith(('Source runtime:','Ready.')):print(line,end='',flush=True)
            if process.wait():raise subprocess.CalledProcessError(process.returncode,command)
        package = base/'runtime-linux-arm64.tar.gz'
        run(['container','cp',state['worker']+':/source-runtime/work/runtime-linux-arm64.tar.gz',package.with_suffix('.partial')])
        package.with_suffix('.partial').replace(package)
        state['ready']=True;state['archive']=str(package);save(base/'setup.json',state)
        control=frozen/'scripts/setup-source-runtime.py'
        (base/'run.sh').write_text('#!/usr/bin/env bash\nset -euo pipefail\nexec '+shlex.join(['python3',str(control),str(base),'--run','--'])+' "$@"\n')
        print('Runtime package: '+str(package),flush=True)
        print('Ready. Run: bash '+shlex.quote(str(base/'run.sh'))+' --describe-runtime',flush=True)
