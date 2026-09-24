"""Shared end-to-end measurement for stateful scenarios and raw MSBuild."""
import json
from pathlib import Path
import subprocess
import time


def command(argv, cwd, log, timeout=None):
    """Keep process startup inside timing; preserve failed samples beside logs."""
    argv = list(map(str, argv))
    log = Path(log)
    start = time.perf_counter()
    result = None
    failure = None
    try:
        with log.open('w') as stream:
            result = subprocess.run(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        failure = str(error)
        raise
    finally:
        seconds = time.perf_counter() - start
        record = dict(command=argv, cwd=str(cwd), wallSeconds=seconds,
                      exitCode=result.returncode if result else None,
                      failure=failure, timingScope='end-to-end')
        log.with_suffix(log.suffix + '.measurement.json').write_text(json.dumps(record, indent=2) + '\n')
    return result, seconds
