"""Check full CMS setup Razor rendering and embedded assets without creating a tenant."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

source = Path(sys.argv[1]).resolve()
evidence = Path(sys.argv[2]).resolve()
name = sys.argv[3]
raw = '--raw' in sys.argv
command = [str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'), str(source/'src/OrchardCore.Cms.Web/bin/Release/net10.0/OrchardCore.Cms.Web.dll')] if raw else [str(source/'bazel-bin/OrchardCore.Cms.Web')]
paths = ['/', '/OrchardCore.Setup/Styles/setup.min.css', '/OrchardCore.Setup/Scripts/setup/setup.min.js', '/OrchardCore.Resources/Vendor/fontawesome-free/css/all.min.css']
rows = []
with (evidence/(name+'.log')).open('w') as log:
    process = subprocess.Popen(command+['--urls', 'http://127.0.0.1:5087'], cwd=source/'src/OrchardCore.Cms.Web' if raw else source, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic()+45
        while True:
            try:
                with urllib.request.urlopen('http://127.0.0.1:5087/', timeout=3) as response:
                    assert response.status == 200
                break
            except urllib.error.URLError:
                if process.poll() is not None or time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        for path in paths:
            with urllib.request.urlopen('http://127.0.0.1:5087'+path, timeout=10) as response:
                body = response.read()
                assert response.status == 200 and len(body) > 1000
                if path == '/':
                    assert b'Orchard' in body and b'<form' in body
                rows.append(dict(path=path, status=response.status, bytes=len(body), contentType=response.headers.get('Content-Type'), sha256=hashlib.sha256(body).hexdigest()))
        (evidence/(name+'.json')).write_text(json.dumps(rows, indent=2))
        print(rows, flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()
