"""Reproduce why file events plus stat data cannot certify unchanged bytes."""
from contextlib import closing
import argparse
import json
import mmap
from pathlib import Path
import select
import tempfile


def probe():
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'input'
        path.write_bytes(b'original')
        with path.open('r+b') as stream, closing(select.kqueue()) as queue:
            event=select.kevent(stream.fileno(),filter=select.KQ_FILTER_VNODE,
                flags=select.KQ_EV_ADD|select.KQ_EV_CLEAR,
                fflags=select.KQ_NOTE_WRITE|select.KQ_NOTE_EXTEND|select.KQ_NOTE_ATTRIB|
                       select.KQ_NOTE_LINK|select.KQ_NOTE_RENAME|select.KQ_NOTE_DELETE|select.KQ_NOTE_REVOKE)
            queue.control([event],0,0)
            with mmap.mmap(stream.fileno(),0) as mapped:
                queue.control(None,16,0)  # mmap creation itself may emit ATTRIB.
                before=path.stat()
                mapped[:]=b'modified'
                after=path.stat()
                events=queue.control(None,16,0)
                return dict(bytesChanged=path.read_bytes()!=b'original',
                    metadataChanged=(before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=
                                    (after.st_size,after.st_mtime_ns,after.st_ctime_ns),
                    events=[e.fflags for e in events],
                    conclusion='Keep full validation for mutable inputs; event absence is not proof')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.write_text(json.dumps(probe(),indent=2)+'\n')
