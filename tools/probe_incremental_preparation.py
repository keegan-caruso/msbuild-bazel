"""Sequential paired experiments; setup and correctness checks are untimed."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time

import discovery_contract as discovery
import preparation_reuse as reuse
from protected_store import ProtectedStore


def probe(source, entries, output, stage, edit=None, repetitions=5):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    local = output / 'source'
    discovery.seal(source, local)
    original = (local / edit).read_bytes() if edit else None
    stores = {mode: ProtectedStore() for mode in ('baseline', 'candidate')}
    report = dict(accepted=False, stage=stage, scope='complete preparation including lease teardown; no build timing',
                  samples=[], setup=[], checks=[], repetitions=repetitions,
                  hostNote='Uncontrolled host load; experiments run serially',
                  code={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (reuse.ROOT/'tools').glob('*.py')})

    def save():
        (output / 'report.json').write_text(json.dumps(report, indent=2)+'\n')

    def measure(mode, index, setup=False):
        target = output / f'{mode}-{index}'
        store = stores[mode] if stage == 'source' or mode == 'candidate' else None
        before = store.statistics() if store else None
        started = time.perf_counter()
        with reuse.prepared_view(local, output/mode, target, entries,
                                 protected_store=store,
                                 incremental_sources=stage == 'source' and mode == 'candidate') as result:
            ready = time.perf_counter()-started
        elapsed = time.perf_counter()-started
        record = dict(mode=mode, index=index, seconds=elapsed, readySeconds=ready, work=result,
                      storeBefore=before, storeAfter=store.statistics() if store else None)
        report['setup' if setup else 'samples'].append(record)
        save()
        if index >= 0:
            if stage == 'store':
                assert result['reused'] and not result['discoveryExecuted'], result
            elif mode == 'candidate':
                assert result['reason'] == 'source-content-changed' and not result['discoveryExecuted'], result
            else:
                assert result['discoveryExecuted'], result
        print(stage, mode, index, round(elapsed, 4), result['reason'], flush=True)
        return target

    try:
        for mode in ('baseline', 'candidate'): measure(mode, -1, True)
        for index in range(repetitions+1):
            if edit:
                (local/edit).write_bytes(original + f'\n// preparation delta {index}\n'.encode())
            targets={}
            for mode in (('baseline','candidate') if index%2 else ('candidate','baseline')):
                targets[mode]=measure(mode, index, index == 0)
            if stage == 'source':
                # Fresh export at the identical sealed path, with identical tools,
                # verifies all graph fields after each derived generation.
                with discovery.qualified_view(local, output/'candidate/discovery', entries,
                                              protected_store=stores['candidate']):
                    fresh=json.loads((output/'candidate/discovery/output/graph.json').read_text())
                    actual=json.loads((targets['candidate']/'graph.json').read_text())
                    assert fresh == actual, 'derived graph differs from fresh export'
                report['checks'].append(dict(index=index, freshGraphEquivalent=True))
            else:
                for mode, target in targets.items():
                    assert reuse.payload_identity(target) == reuse.payload_identity(output/f'{mode}--1'), 'unchanged payload differs from seed'
                state=output/'candidate'
                generation=json.loads((state/'current.json').read_text())['generation']
                certificate=json.loads((state/'generations'/generation/'manifest.json').read_text())['certificate']
                reuse.verify_view(certificate)  # Untimed strict full-content check.
                report['checks'].append(dict(index=index, payloadEquivalentToSeed=True, strictVerification=True))
            save()
        report['summary']={mode:dict(median=statistics.median(values), minimum=min(values), maximum=max(values))
                           for mode in ('baseline','candidate')
                           if (values:=[s['seconds'] for s in report['samples'] if s['mode']==mode])}
        before=report['summary']['baseline']['median'];after=report['summary']['candidate']['median']
        report.update(reduction=1-after/before, secondsSaved=before-after,
                      meaningful=1-after/before >= .1 and before-after >= .1, accepted=True)
    except BaseException as error:
        report['error']=dict(type=type(error).__name__, message=str(error))
        raise
    finally: save()
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','entries','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--stage',choices=('store','source'),required=True)
    parser.add_argument('--edit')
    args=parser.parse_args()
    if args.stage == 'source' and not args.edit: parser.error('--edit required for source stage')
    probe(args.source,json.loads(args.entries.read_text()),args.output,args.stage,args.edit)
