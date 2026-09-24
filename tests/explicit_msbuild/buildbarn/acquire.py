import hashlib,io,json,tarfile,urllib.parse,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parent;out=root/'bin';out.mkdir(exist_ok=True)
images={
 'bb-worker':'sha256:4cc65f0dd716fd0942ccc0fdd770421065b7f3bf55062a184c4376e4c0a4a13e',
 'bb-scheduler':'sha256:95417d159b5b9f17a6c915fec43603be51c553f68de439a9affcfe811bd0c6da',
 'bb-storage':'sha256:36201141f924865ddbea1bc518c4f98dd0dbb744181ef34f9f5e864d3dcf43f8',
 'bb-runner-bare':'sha256:016c8b2d586ef6cfaa1b1af5d1c663a7a163cea01b88b11ceaf03471cef21107',
};records=[]
for name,index in images.items():
 q=urllib.parse.urlencode(dict(service='ghcr.io',scope='repository:buildbarn/'+name+':pull'))
 token=json.load(urllib.request.urlopen('https://ghcr.io/token?'+q))['token']
 def fetch(kind,digest):
  req=urllib.request.Request('https://ghcr.io/v2/buildbarn/'+name+'/'+kind+'/'+digest,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json'})
  data=urllib.request.urlopen(req).read();assert 'sha256:'+hashlib.sha256(data).hexdigest()==digest;return data
 idx=json.loads(fetch('manifests',index));platform=next(m for m in idx['manifests'] if m.get('platform',{}).get('os')=='linux' and m['platform'].get('architecture')=='arm64')
 manifest=json.loads(fetch('manifests',platform['digest']));members=[];binary={'bb-runner-bare':'bb_runner'}.get(name,name.replace('-','_'));found=None
 for layer in manifest['layers']:
  with tarfile.open(fileobj=io.BytesIO(fetch('blobs',layer['digest']))) as archive:
   for member in archive:
    members.append((member.name,member.type.decode(),member.linkname))
    if member.isfile() and Path(member.name).name==binary:
     data=archive.extractfile(member).read();(out/binary).write_bytes(data);(out/binary).chmod(0o755);found=hashlib.sha256(data).hexdigest()
 assert found,(binary,[m for m in members if 'runner' in m[0]])
 records.append(dict(image='ghcr.io/buildbarn/'+name,index=index,platformManifest=platform['digest'],binary=binary,sha256=found))
 print(binary,found,flush=True)
(root/'images.json').write_text(json.dumps(records,indent=2)+'\n')
