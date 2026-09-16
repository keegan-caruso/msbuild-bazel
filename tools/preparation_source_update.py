"""Refresh content hashes without reevaluating a qualified compile-only graph.

Only existing C# compile inputs may change. Namespace, modes, imports, restore,
package and every other declared domain remain byte-identical. Resource-bearing
or additional-input graphs retain full discovery because SDK tasks may inspect
source contents while computing resource metadata.
"""
import copy
from pathlib import PurePosixPath
from preparation_identity import compare, digest


def refresh(candidate, graph, current):
    if digest(graph) != candidate['graphSha256']: return None
    if compare(candidate['identity'], current)['changedDomains'] != ['root:workspace']: return None
    inputs=graph.get('graphInputs',[])+[item for node in graph['nodes'] for item in node['inputs']]
    if any(item['kind'] in ('resource','additional') for item in inputs): return None
    roles={}
    for item in inputs: roles.setdefault(item['path'],set()).add(item['kind'])
    allowed={path for path,kinds in roles.items() if kinds=={'source'} and path.startswith('workspace/') and PurePosixPath(path).suffix=='.cs'}
    previous={e['path']:e for e in candidate['identity']['snapshots']['workspace']['entries']}
    updated={e['path']:e for e in current['snapshots']['workspace']['entries']}
    if previous.keys()!=updated.keys(): return None
    changed={}
    for path,old in previous.items():
        new=updated[path]
        if old==new: continue
        logical='workspace/'+path.removeprefix('./')
        if logical not in allowed or old['kind']!='file' or new['kind']!='file': return None
        if {k:v for k,v in old.items() if k not in ('size','sha256')} != {k:v for k,v in new.items() if k not in ('size','sha256')}: return None
        changed[logical]=new['sha256']
    if not changed: return None
    result=copy.deepcopy(graph)
    for item in result.get('graphInputs',[])+[item for node in result['nodes'] for item in node['inputs']]:
        if item['path'] in changed:
            old=previous['./'+item['path'].removeprefix('workspace/')]
            if item['sha256']!=old['sha256']: return None
            item['sha256']=changed[item['path']]
    certificate={k:copy.deepcopy(v) for k,v in candidate.items() if k not in ('sha256','derivation')}
    certificate.update(identity=current,graphSha256=digest(result),derivation=dict(policy='compile-content-only-v1',parentCertificate=candidate['sha256'],changedSources=sorted(changed)))
    certificate['sha256']=digest(certificate)
    return result,certificate
