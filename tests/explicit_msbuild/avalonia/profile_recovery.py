"""Repeated fresh-server recovery profiles; no source edits or local launches."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from remote_support import RemoteFixture

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('workspace', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--executor', required=True)
p.add_argument('--repetitions', type=int, default=3)
p.add_argument('--modes', nargs='+', choices=['all', 'toplevel', 'minimal'], default=['all', 'toplevel', 'minimal'])
a = p.parse_args()
assert a.repetitions > 0
workspace = a.workspace.resolve()
a.output = a.output.resolve()
a.output.mkdir(parents=True, exist_ok=False)

def network():
    # Container network counters include RPC/repository traffic, not just CAS bytes.
    rows = [line.split(':', 1) for line in Path('/proc/net/dev').read_text().splitlines() if ':' in line]
    return {name.strip(): [int(data.split()[0]), int(data.split()[8])]
            for name, data in rows if name.strip() != 'lo'}

records = []
for repeat in range(a.repetitions):
    # Rotate order so one policy does not always inherit the warmest host caches.
    modes = a.modes[repeat % len(a.modes):] + a.modes[:repeat % len(a.modes)]
    for mode in modes:
        f = RemoteFixture(a.output / (mode + '-' + str(repeat)), a.executor, workspace,
                          instance=(workspace / 'remote-instance.txt').read_text())
        f.sdk()
        before = network()
        try:
            actions = f.run('recovery', ['//:theme_test'], [], tests=[], downloads=mode,
                            extra_args=['--profile=' + str(f.folder / 'profile.json.gz'),
                                        '--build_event_json_file=' + str(f.folder / 'events.json'),
                                        '--experimental_profile_additional_tasks=remote_network'])
            after = network()
            assert actions and all(x['cacheHit'] for x in actions)
            assert any(x['mnemonic'] == 'TestRunner' for x in actions)
            record = dict(mode=mode,repeat=repeat,seconds=f.rows[-1]['seconds'],
                          receivedBytes=sum(after[k][0]-v[0] for k,v in before.items()),
                          sentBytes=sum(after[k][1]-v[1] for k,v in before.items()),
                          cacheHits=len(actions))
            records.append(record)
            (a.output / 'samples.json').write_text(json.dumps(records, indent=2) + '\n')
            print(json.dumps(record), flush=True)
        finally:
            f.shutdown()
