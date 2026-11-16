"""Sample whole-guest Linux memory; disk totals are measured between commands."""
import os
from pathlib import Path
import subprocess
import threading
import time


def allocated_bytes(paths):
    """Count allocated blocks once across the supplied, non-overlapping roots."""
    paths = [str(Path(path)) for path in paths if Path(path).exists()]
    if not paths:
        return 0
    output = subprocess.check_output(['du', '-sk', *paths], text=True)
    return sum(int(line.split()[0]) * 1024 for line in output.splitlines())


class GuestMemory:
    def __init__(self, interval=.25):
        self.interval = interval
        self.samples = []
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self):
        start = time.monotonic()
        while True:
            memory = {line.split(':')[0]: int(line.split()[1])
                      for line in Path('/proc/meminfo').read_text().splitlines()}
            rss = 0
            for process in Path('/proc').glob('[0-9]*/statm'):
                try:
                    rss += int(process.read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
                except (OSError, ValueError, IndexError):
                    continue  # A process may exit between enumeration and reading.
            self.samples.append(dict(seconds=time.monotonic()-start,
                                     totalKiB=memory['MemTotal'], availableKiB=memory['MemAvailable'],
                                     summedProcessRssBytes=rss))
            if self.stopped.wait(self.interval):
                return

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stopped.set()
        self.thread.join()

    def summary(self):
        if not self.samples:
            raise RuntimeError('No guest memory observations recorded')
        return dict(sampleIntervalSeconds=self.interval,
                    minimumAvailableKiB=min(row['availableKiB'] for row in self.samples),
                    maximumUsedKiB=max(row['totalKiB']-row['availableKiB'] for row in self.samples),
                    peakSummedProcessRssBytes=max(row['summedProcessRssBytes'] for row in self.samples),
                    rssScope='all guest processes; shared pages counted per process')
