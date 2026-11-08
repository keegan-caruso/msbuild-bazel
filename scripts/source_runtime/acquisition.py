"""Acquire the locked source through Bazel's downloader and repository cache."""
import json
from pathlib import Path
import subprocess

from .common import ROOT


def acquire_source(base, source, environment, supplied=None):
    workspace=base/'source-acquisition'
    workspace.mkdir(exist_ok=True)
    url=supplied.resolve().as_uri() if supplied else source['url']
    (workspace/'MODULE.bazel').write_text('module(name="runtime_source_acquisition")\n'
        'http_file=use_repo_rule("@bazel_tools//tools/build_defs/repo:http.bzl","http_file")\n'
        'http_file(name="runtime_source",url='+json.dumps(url)+',sha256='+json.dumps(source['sha256'])+
        ',downloaded_file_path="runtime.tar.gz")\n')
    (workspace/'BUILD.bazel').write_text('alias(name="source",actual="@runtime_source//file")\n')
    command=[str(ROOT/'scripts/bazel-launcher.sh'),'--nosystem_rc','--nohome_rc','--noworkspace_rc',
        '--output_base='+str(base/'source-acquisition-bazel')]
    try:
        with (base/'reports/source-acquisition.log').open('w') as log:
            result=subprocess.run(command+['cquery','//:source','--output=files'],cwd=workspace,env=environment,
                text=True,stdout=subprocess.PIPE,stderr=log,check=True)
        files=result.stdout.splitlines()
        if len(files)!=1:
            raise ValueError('Source acquisition must produce one archive')
        output_base=subprocess.check_output(command+['info','output_base'],cwd=workspace,env=environment,
            text=True,stderr=subprocess.DEVNULL).strip()
        # Repository source artifacts exist before an action creates the
        # execroot symlink forest. Resolve against Bazel's repository store.
        if not files[0].startswith('external/') or '..' in Path(files[0]).parts:
            raise ValueError('Expected a Bazel repository source artifact')
        return (Path(output_base)/files[0]).resolve(strict=True)
    finally:
        subprocess.run(command+['shutdown'],cwd=workspace,env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
