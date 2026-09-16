"""Measure rebuilding the trusted-store session on every preparation request.

This isolates cache lifetime from persistent-process measurements. Interpreter
startup is excluded from both sides; preparation and teardown remain timed.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
import probe_incremental_preparation as benchmark
from protected_store import ProtectedStore


class FreshSession:
    def __init__(self):
        self.store=ProtectedStore()
        self.before=True

    def snapshot(self,*args):
        return self.store.snapshot(*args)

    def statistics(self):
        # The benchmark takes one statistics snapshot before and one after each
        # timed request. Reconstruct the cache before the timer starts; its first
        # full verification still occurs within the timed preparation.
        if self.before:self.store=ProtectedStore()
        self.before=not self.before
        return self.store.statistics()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','entries','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    benchmark.ProtectedStore=FreshSession
    result=benchmark.probe(args.source,json.loads(args.entries.read_text()),args.output,'store')
    result['sessionLifetime']='fresh cache per request; excludes interpreter startup'
    (args.output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
