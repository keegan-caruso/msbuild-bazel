"""One owned Apple Container for the source-runtime developer workflow."""
import fcntl
import importlib.util
import json
import os
import stat
import platform
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import uuid
from urllib.parse import urlsplit

from .common import ROOT, stage_source, digest, read_recipe, run, save, rules_identity, selected_bazel_version, validate_bazel_version, project_cache_read_only, bazel_cache_read_only


def demo_helpers():
    spec = importlib.util.spec_from_file_location('runtime_demo_control', ROOT/'scripts/setup-runtime-demo.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELAY_SOCKET = '/var/host-services/shared-cache.sock'


def cache_socket(cache_url, state=None):
    supplied = os.environ.get('RULES_MSBUILD_SHARED_CACHE_SOCKET') or None
    recorded = state.get('cacheSocket') if state is not None else None
    if supplied:
        supplied = str(Path(supplied).expanduser().resolve())
    if state is not None and supplied is not None and supplied != recorded:
        raise ValueError('Shared cache socket changed; use a fresh directory')
    socket_path = recorded if state is not None else supplied
    if socket_path:
        spec = importlib.util.spec_from_file_location('shared_cache_guest_relay', ROOT/'scripts/shared-cache-guest-relay.py')
        relay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(relay)
        relay.endpoint(cache_url or '')
        parsed = urlsplit(cache_url)
        if parsed.query or parsed.fragment:
            raise ValueError('Shared cache relay URL cannot contain a query or fragment')
        try:
            valid = stat.S_ISSOCK(Path(socket_path).stat().st_mode)
        except OSError:
            valid = False
        if not valid:
            raise ValueError('Shared cache relay requires an existing host UNIX socket')
    return socket_path


def validate_relay_mount(worker, socket_path):
    if not socket_path:
        return
    mounts = worker['configuration'].get('mounts', [])
    matches = [mount for mount in mounts if mount.get('destination') == RELAY_SOCKET]
    if len(matches) != 1 or matches[0].get('source') != socket_path:
        raise ValueError('Source-runtime worker shared cache socket mount differs from setup')


def start_relay(worker, cache_url):
    # The worker outlives container exec. A PID check keeps repeated setup/run
    # calls idempotent while rejecting stale ready files after a worker restart.
    script = r'''set -eu
pidfile=/tmp/rules-msbuild-source-runtime-relay.pid
ready=/tmp/rules-msbuild-source-runtime-relay.ready
if [ -f "$pidfile" ]; then
    pid=$(cat "$pidfile")
    case "$pid" in ''|*[!0-9]*) exit 1;; esac
    if [ -r "/proc/$pid/cmdline" ] && tr '\0' '\n' < "/proc/$pid/cmdline" | grep -Fxq /source-runtime/rules/scripts/shared-cache-guest-relay.py; then
        [ -f "$ready" ] && exit 0
        kill "$pid" 2>/dev/null || :
    fi
fi
rm -f "$ready" "$pidfile"
nohup python3 /source-runtime/rules/scripts/shared-cache-guest-relay.py --url "$1" --socket /var/host-services/shared-cache.sock --ready "$ready" >/tmp/rules-msbuild-source-runtime-relay.log 2>&1 </dev/null &
pid=$!
echo "$pid" > "$pidfile"
for attempt in $(seq 1 100); do
    kill -0 "$pid" 2>/dev/null || { cat /tmp/rules-msbuild-source-runtime-relay.log >&2; rm -f "$ready" "$pidfile"; exit 1; }
    [ -f "$ready" ] && exit 0
    sleep 0.1
done
kill "$pid" 2>/dev/null || :
rm -f "$ready" "$pidfile"
echo 'Shared cache relay startup timed out' >&2; exit 1
'''
    run(['container', 'exec', worker, 'sh', '-c', script, 'relay', cache_url])


def worker_memory(state, supplied=None):
    recorded = state.get('workerMemoryGiB', 8)
    if type(recorded) is not int or recorded <= 0:
        raise ValueError('Invalid saved worker memory')
    if supplied is not None and supplied != recorded:
        raise ValueError('Worker memory changed; use a fresh directory')
    return recorded


def validate_worker_memory(worker, memory):
    if worker['configuration'].get('resources', {}).get('memoryInBytes') != memory * 1024**3:
        raise ValueError('Source-runtime worker memory differs from setup')


def operate(args, application):
    base = args.output.expanduser().resolve()
    with (base/'setup.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state = json.loads((base/'setup.json').read_text())
        if state.get('kind') != 'apple-source-runtime':
            raise ValueError('Output belongs to another workflow')
        if not state.get('ready'):
            raise ValueError('Complete setup with --resume before running the app')
        read_only = project_cache_read_only(state)
        bazel_readonly = bazel_cache_read_only(state, getattr(args, 'bazel_cache_read_only', None))
        memory = worker_memory(state, getattr(args, 'worker_memory_gib', None))
        socket_path = cache_socket(state.get('cacheUrl'), state)
        helpers = demo_helpers()
        worker = helpers.inspect(state['worker'])
        if not worker or worker['configuration']['labels'].get('rules-msbuild.source-runtime') != state['id']:
            raise ValueError('Source-runtime worker is missing or has different ownership')
        if worker['configuration']['image']['descriptor']['digest'] != state['image'].split('@',1)[1]:
            raise ValueError('Source-runtime worker image differs from setup')
        validate_worker_memory(worker, memory)
        validate_relay_mount(worker, socket_path)
        if worker['status']['state'] != 'running':
            run(['container','start',state['worker']])
        if socket_path:
            start_relay(state['worker'], state['cacheUrl'])
        command = ['container','exec','--env','RULES_MSBUILD_PROJECT_CACHE_READ_ONLY='+read_only,state['worker'],'python3','/source-runtime/rules/scripts/setup-source-runtime.py',
                   '/source-runtime/work','--test' if args.test else '--run']
        if bazel_readonly: command.append('--bazel-cache-read-only')
        if application: command += ['--', *application]
        return subprocess.run(command).returncode


def setup(args):
    if platform.machine() != 'arm64' or not shutil.which('container'):
        raise ValueError('Apple silicon and Apple Container are required')
    if args.native_toolchain or args.sandbox or args.registry or args.repository_cache or args.host_space_path:
        raise ValueError('Native tool/cache paths are Linux options; Apple setup creates its own declared environment')
    base = args.output.expanduser().resolve()
    helpers = demo_helpers()
    if base.exists() and not args.resume:
        state_path = base/'setup.json'
        if not state_path.is_file():
            raise ValueError('Refusing to resume an unowned output directory')
        recorded = json.loads(state_path.read_text())
        if recorded.get('kind') != 'apple-source-runtime' or recorded.get('version') != 1 or recorded.get('sourceIdentity') != rules_identity():
            raise ValueError('Automatic resume requires matching owned setup inputs')
        args.resume = True
    if args.resume:
        state = json.loads((base/'setup.json').read_text())
        if state.get('kind') != 'apple-source-runtime' or state.get('version') != 1:
            raise ValueError('Output belongs to another workflow')
        for supplied,recorded in [(args.image,state['requestedImage']),(args.cache_url,state['cacheUrl'])]:
            if supplied is not None and supplied != recorded:
                raise ValueError('Setup options changed; use a fresh directory')
        validate_bazel_version(state)
        project_cache_read_only(state)
        memory = worker_memory(state, getattr(args, 'worker_memory_gib', None))
        bazel_readonly = bazel_cache_read_only(state, getattr(args, 'bazel_cache_read_only', None))
        socket_path = cache_socket(state['cacheUrl'], state)
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
        memory = getattr(args, 'worker_memory_gib', None)
        if memory is None:
            memory = 8
        if type(memory) is not int or memory <= 0:
            raise ValueError('Worker memory must be a positive integer in GiB')
        bazel_readonly = bazel_cache_read_only(None, getattr(args, 'bazel_cache_read_only', None))
        socket_path = cache_socket(args.cache_url)
        base.mkdir(parents=True,mode=0o700)
        identifier = uuid.uuid4().hex[:10]
        archive = base/'rules.tar'
        state = dict(projectCacheReadOnly=project_cache_read_only(),bazelVersion=selected_bazel_version(),version=1,kind='apple-source-runtime',id=identifier,worker='msbuild-source-runtime-'+identifier,
                     requestedImage=args.image,cacheUrl=args.cache_url,cacheSocket=socket_path,workerMemoryGiB=memory,bazelCacheReadOnly=bazel_readonly,sourceIdentity=rules_identity(),rulesSha256=helpers.snapshot(archive),ready=False)
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
            validate_worker_memory(worker, memory)
            validate_relay_mount(worker, socket_path)
            if worker['status']['state']!='running':run(['container','start',state['worker']])
        else:
            mount = ['--volume', socket_path+':'+RELAY_SOCKET] if socket_path else []
            run(['container','run','-d','--init','--arch','arm64','--name',state['worker'],'--cpus','4','--memory',str(memory)+'G',
                 '--cap-add','SYS_ADMIN','--masked-path','NONE','--read-only-path','NONE',
                 '--label','rules-msbuild.source-runtime='+state['id'],'--volume',str(base)+':/host:ro',*mount,state['image'],'sleep','infinity'])
        run(['container','exec',state['worker'],'mkdir','-p','/source-runtime/rules'])
        run(['container','exec',state['worker'],'tar','-xf','/host/rules.tar','-C','/source-runtime/rules'])
        if socket_path:
            start_relay(state['worker'], state['cacheUrl'])
        command=['container','exec','--env','USE_BAZEL_VERSION='+state['bazelVersion'],'--env','RULES_MSBUILD_PROJECT_CACHE_READ_ONLY='+project_cache_read_only(state),state['worker'],'python3','/source-runtime/rules/scripts/setup-source-runtime.py',
                 '/source-runtime/work','--host-space-path=/host']
        if state['cacheUrl']:command+=['--cache-url='+state['cacheUrl']]
        if bazel_readonly:command+=['--bazel-cache-read-only']
        if args.source_archive:
            source=read_recipe()['source']
            stage_source(base/'runtime-source.tar.gz',source['sha256'],args.source_archive.resolve())
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
