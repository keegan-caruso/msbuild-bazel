"""Eligibility for the owned package-free native cache contract."""
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from discovery_contract import check_xml, SDK_SWITCHES
from preparation_identity import tree_snapshot


def qualify(root):
    # Reuse namespace/content capture and authored XML grammar, then narrow it to
    # the owned fixture's package-free SDK-only execution surface.
    tree_snapshot(root,[root])
    sdk=json.loads((root/'global.json').read_text()).get('sdk',{})
    if sdk!={'version':'10.0.400','rollForward':'disable'}:raise ValueError('unqualified SDK selection')
    projects={};kinds={}
    for p in root.rglob('*.csproj'):
        rel=p.relative_to(root)
        if len(rel.parts)!=2 or p.stem!=p.parent.name:raise ValueError('unqualified project layout')
        check_xml(p); tree=ET.parse(p)
        allowed={'Project','PropertyGroup','ItemGroup','ProjectReference','OutputType'}
        if any(e.tag not in allowed for e in tree.iter()):raise ValueError('unqualified project XML')
        kinds[str(p.relative_to(root))]=tree.findtext('PropertyGroup/OutputType','Library')
        if kinds[str(p.relative_to(root))] not in ('Library','Exe'):raise ValueError('unqualified output type')
        if any('$' in (e.text or '') for e in tree.iter()):raise ValueError('project property expressions unsupported')
        deps=[]
        for e in tree.iter():
            if e.tag=='ProjectReference':
                if set(e.attrib)!={'Include'}:raise ValueError('unqualified reference metadata')
                deps.append(str((p.parent/e.attrib['Include']).resolve().relative_to(root)))
            elif e.tag!='Project' and e.attrib:raise ValueError('unqualified project attributes')
        projects[str(p.relative_to(root))]=sorted(deps)
    if len({Path(p).stem for p in projects})!=len(projects):raise ValueError('assembly name collision')
    if any(kinds.get(d)!='Library' for deps in projects.values() for d in deps):raise ValueError('unqualified dependency')
    props=root/'Directory.Build.props';check_xml(props)
    allowed={'Project','PropertyGroup','TargetFramework','UseAppHost','UseSharedCompilation','EnableNETAnalyzers','Deterministic','DisableTransitiveProjectReferences','Nullable','DefineConstants'}
    if any(e.tag not in allowed or e.attrib or ('$' in (e.text or '')) for e in ET.parse(props).iter()):raise ValueError('unqualified props')
    values={e.tag:(e.text or '').strip() for e in ET.parse(props).iter()}
    if values.get('TargetFramework')!='net10.0' or any(values.get(k)!=v for k,v in SDK_SWITCHES.items()):raise ValueError('required SDK switches missing or changed')
    for p in root.rglob('*'):
        if p.is_symlink():raise ValueError('fixture symlinks unsupported')
        if not p.is_file():continue
        rel=p.relative_to(root)
        if p.name in ('global.json','NuGet.Config','Directory.Build.props','synthetic.json') and len(rel.parts)!=1:raise ValueError('nested control file unsupported')
        if p.suffix=='.cs' and rel.parts[0] not in {str(Path(project).parent) for project in projects}:raise ValueError('source outside declared projects')
        if 'obj' in rel.parts:
            if len(rel.parts)!=3 or p.suffix not in ('.json','.props','.targets') and p.name!='project.nuget.cache':raise ValueError('unexpected restore input')
            if p.suffix in ('.props','.targets'):
                check_xml(p)
                if any(e.tag.rsplit('}',1)[-1]=='Import' for e in ET.parse(p).iter()):raise ValueError('restore imports unsupported')
            if p.name=='project.assets.json' and any(v['type']!='project' for v in json.loads(p.read_text())['libraries'].values()):raise ValueError('packages unsupported')
        elif p.name not in ('global.json','NuGet.Config','Directory.Build.props','synthetic.json') and p.suffix not in ('.cs','.csproj'):
            raise ValueError('undeclared fixture input: '+str(rel))
    return projects

