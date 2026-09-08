#!/usr/bin/env python3
"""Scan pinned public source archives for time reads; this is not execution proof."""
import argparse
import concurrent.futures
import datetime
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import urllib.request

PATTERN = re.compile(
    r'(?:DateTime(?:Offset)?|datetime|DateOnly)\s*(?:\.|\]\s*::)\s*(?:Now|UtcNow|Today|now|utcnow|today)\b'
    r'|(?:ModifiedTime|CreatedTime|AccessedTime|LastWriteTime(?:Utc)?|CreationTime(?:Utc)?|LastAccessTime(?:Utc)?)\b'
    r'|Get(?:LastWrite|Creation|LastAccess)Time(?:Utc)?\b'
    r'|TimeProvider\s*\.\s*System|\bGetUtcNow\s*\('
    r'|\bDate\s*\.\s*now\s*\(|\bnew\s+Date\s*\(\s*\)'
    r'|\btime\.(?:time|ctime|localtime|gmtime)\s*\(|\bos\.path\.get(?:m|c|a)time\b'
    r'|\bst_[mca]time(?:_ns)?\b|\btime\.Now\s*\('
    r'|SOURCE_DATE_EPOCH|\b(?:__DATE__|__TIME__)\b'
    r'|\bGet-Date\b|\$\([^\n]*\bdate\s|`date\b|\bdate\s+[-+]|%(?:date|time)%'
    r'|string\s*\(\s*TIMESTAMP|file\s*\(\s*TIMESTAMP'
    r'|\b(?:BuildDate|BuildTimestamp|BuildTimeStamp|TimestampUtc)\b', re.I)
EXTENSIONS = {'.cs','.fs','.vb','.csx','.props','.targets','.proj','.csproj','.fsproj','.vbproj',
    '.projitems','.shproj','.sh','.ps1','.psm1','.cmd','.bat','.py','.js','.ts','.mjs','.cjs',
    '.json','.yml','.yaml','.xml','.config','.cmake','.txt','.c','.cc','.cpp','.h','.hpp','.go',
    '.bzl','.bazel','.cake','.in','.tt','.ttinclude','.razor','.cshtml'}
BUILD_EXTENSIONS = {'.props','.targets','.proj','.csproj','.fsproj','.vbproj','.projitems',
    '.shproj','.sh','.ps1','.psm1','.cmd','.bat','.cmake','.bzl','.bazel','.cake','.tt','.ttinclude'}

def build_candidate(path):
    p = PurePosixPath(path)
    return (p.suffix.lower() in BUILD_EXTENSIONS or p.name in ('CMakeLists.txt','Makefile','Dockerfile')
        or bool(re.search(r'(^|/)(eng|build|builds|buildscripts|scripts|nukebuild|\.build|\.github|tools)(/|$)',path,re.I))
        or bool(re.search(r'generator|build\.tasks|msbuild|buildintegration|designtime|versioning',path,re.I)))

def inspect(entry, output):
    result = dict(entry, status='started', files=0, textFiles=0, bytesScanned=0, skippedLarge=[], hits=[])
    root = output / entry['repository'].replace('/','--')
    root.mkdir(parents=True, exist_ok=True)
    try:
        revision = entry.get('revision')
        if not revision:
            remote = subprocess.run(['git','ls-remote','https://github.com/'+entry['repository']+'.git','HEAD'],
                text=True, capture_output=True, check=True, timeout=60).stdout.split()
            revision = remote[0]
            if not re.fullmatch('[0-9a-f]{40}',revision):
                raise ValueError('invalid resolved revision')
        result.update(revision=revision, revisionSource=entry.get('revisionSource',
            'testing-plan' if entry.get('revision') else 'default-HEAD-at-audit'))
        url = 'https://codeload.github.com/'+entry['repository']+'/tar.gz/'+revision
        result['archiveUrl'] = url
        print('START '+entry['repository']+' '+revision, flush=True)
        with urllib.request.urlopen(url,timeout=90) as response:
            with tarfile.open(fileobj=response,mode='r|gz') as archive:
                for member in archive:
                    if not member.isfile():
                        continue
                    result['files'] += 1
                    path = PurePosixPath(*PurePosixPath(member.name).parts[1:])
                    if path.is_absolute() or '..' in path.parts:
                        raise ValueError('unsafe archive path')
                    if path.suffix.lower() not in EXTENSIONS and path.name not in ('Dockerfile','Makefile','CMakeLists.txt','BUILD','WORKSPACE'):
                        continue
                    if member.size > 8_000_000:
                        result['skippedLarge'].append(str(path))
                        continue
                    raw = archive.extractfile(member).read()
                    if b'\0' in raw[:2048]:
                        continue
                    value = raw.decode('utf-8-sig',errors='replace')
                    result['textFiles'] += 1
                    result['bytesScanned'] += len(raw)
                    hits = [dict(path=str(path),line=i,text=line.strip()[:1200],buildCandidate=build_candidate(str(path)))
                        for i,line in enumerate(value.splitlines(),1) if PATTERN.search(line)]
                    result['hits'].extend(hits)
                    if hits or build_candidate(str(path)):
                        target = root/'source'/path
                        target.parent.mkdir(parents=True,exist_ok=True)
                        target.write_text(value)
        result['status']='scanned'
        result['buildCandidateHits']=sum(h['buildCandidate'] for h in result['hits'])
    except Exception as error:
        result.update(status='failed',error=str(error))
    (root/'scan.json').write_text(json.dumps(result,indent=2)+'\n')
    print('END '+entry['repository']+' '+result['status']+' text='+str(result['textFiles'])+' hits='+str(len(result['hits']))+' build='+str(result.get('buildCandidateHits',0)),flush=True)
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projects',type=Path,default=Path(__file__).with_name('time-audit-projects.json'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    if args.workers < 1:
        parser.error('--workers must be positive')
    args.output.mkdir(parents=True,exist_ok=False)
    projects=json.loads(args.projects.read_text())
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending=[pool.submit(inspect,p,args.output) for p in projects]
        for future in concurrent.futures.as_completed(pending):
            results.append(future.result())
            (args.output/'summary.json').write_text(json.dumps(dict(
                inspectedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                projects=[{k:v for k,v in r.items() if k!='hits'} for r in results]),indent=2)+'\n')
    if any(r['status']!='scanned' for r in results):
        raise SystemExit(1)

if __name__=='__main__':
    main()
