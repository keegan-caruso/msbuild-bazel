#!/usr/bin/env python3
"""Build a pinned source runtime and run an app with the graph/plugin workflow."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
from urllib.parse import urlsplit

from source_runtime.linux import build_command, setup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='owned setup directory; retain it for run and resume')
    parser.add_argument('--resume', action='store_true', help='explicit resume; matching owned inputs resume automatically')
    parser.add_argument('--image', help='Apple Container native environment pinned by @sha256; default builds the supplied image')
    parser.add_argument('--run', action='store_true', help='run the app from a completed setup; remaining arguments go to the app')
    parser.add_argument('--test', action='store_true', help='actually execute the prepared app test')
    parser.add_argument('--cache-url', help='optional Bazel and project AC/CAS endpoint')
    parser.add_argument('--registry', help='optional verified Bazel registry URL')
    parser.add_argument('--repository-cache', type=Path, help='optional acquisition cache')
    parser.add_argument('--host-space-path', type=Path, help='physical host filesystem mount when running inside a VM')
    parser.add_argument('--source-archive', type=Path, help='optional cached copy of the pinned runtime source')
    parser.add_argument('--native-toolchain', type=Path, help='optional previously recorded native tool filesystem archive')
    parser.add_argument('--sandbox', type=Path, help='bubblewrap paired with --native-toolchain')
    args, application = parser.parse_known_args()
    if application and application[0] == '--':
        application = application[1:]
    if args.run and args.test or application and not args.run:
        parser.error('App arguments require --run; choose run or test')
    if args.cache_url:
        address=urlsplit(args.cache_url)
        if address.scheme not in ['http','https'] or not address.hostname or address.username or address.password or address.query or address.fragment:
            parser.error('--cache-url requires an HTTP(S) endpoint without embedded credentials')
    if platform.system() == 'Darwin':
        from source_runtime import apple
        if args.run or args.test:
            raise SystemExit(apple.operate(args, application))
        apple.setup(args)
        return
    if args.image:
        parser.error('--image is an Apple Container setup option')
    if args.run or args.test:
        state = json.loads((args.output/'setup.json').read_text())
        if not state.get('ready'):
            parser.error('Complete setup first, using --resume after interruption')
        command, cwd, env = build_command(args.output.resolve(), 'run' if args.run else 'test', application)
        raise SystemExit(subprocess.run(command, cwd=cwd, env=env).returncode)
    setup(args)


if __name__ == '__main__':
    main()
