"""Untimed work counters for the paired materialization fixture."""
import argparse
from collections import Counter
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
from unittest.mock import patch
import zipfile

from probe_materialization_scaling import BASELINE, fixture, inventory, previous
import prepare_graph


def probe(output, count=100):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    source=output/'source';graph=fixture(source,count,'chain')
    report=dict(scope='untimed instrumented work counts', projects=count, variants={})
    expected=None
    for revision in (BASELINE,'3ff54ea','current'):
        module=prepare_graph if revision=='current' else previous('prepare_graph',revision)
        if revision!='current':module.graph_packages=previous('graph_packages',revision)
        target=output/'generated';target.mkdir();(target/'restore').mkdir()
        counts=Counter()
        def counted(name, function, path_index=None):
            def call(*args,**kwargs):
                result=function(*args,**kwargs)
                counts[name+'Calls']+=1
                if path_index is not None:counts[name+'Bytes']+=Path(args[path_index]).stat().st_size
                return result
            return call
        with ExitStack() as stack:
            for owner,name,label,index in ((Path,'read_text','textRead',0),(Path,'read_bytes','byteRead',0),
                                          (shutil,'copyfile','sourceCopy',0),(zipfile.ZipFile,'__init__','archiveOpen',None)):
                stack.enter_context(patch.object(owner,name,counted(label,getattr(owner,name),index)))
            if hasattr(module.graph_packages,'StagingSession'):
                owner=module.graph_packages.StagingSession
                stack.enter_context(patch.object(owner,'read',counted('sessionRead',owner.read,1)))
            module.write_build(source,graph,target)
        actual=inventory(target)
        if expected is None:expected=actual
        assert expected==actual
        report['variants'][revision]=dict(counts)
        shutil.rmtree(target)
    report['equivalent']=True
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    probe(parser.parse_args().output)
