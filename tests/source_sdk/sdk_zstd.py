"""Losslessly recompress the upstream SDK tar stream; never rewrite its members."""
import gzip
import hashlib
import json
from pathlib import Path
import platform
import sys


def recompress(source, output, provenance):
    from compression import zstd

    if sys.version_info[:2] != (3, 14) or zstd.zstd_version_info != (1, 5, 7):
        raise ValueError('SDK compression requires Python 3.14 and libzstd 1.5.7')
    options = {
        zstd.CompressionParameter.compression_level: 9,
        zstd.CompressionParameter.window_log: 26,
        zstd.CompressionParameter.enable_long_distance_matching: 1,
        zstd.CompressionParameter.checksum_flag: 1,
        zstd.CompressionParameter.nb_workers: 0,
    }
    tar_digest = hashlib.sha256()
    with gzip.open(source, 'rb') as original, zstd.open(output, 'wb', options=options) as compressed:
        for chunk in iter(lambda: original.read(1024 * 1024), b''):
            tar_digest.update(chunk)
            compressed.write(chunk)
    def digest(path):
        with open(path, 'rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    Path(provenance).write_text(json.dumps({
        'upstreamGzipSha256': digest(source),
        'tarSha256': tar_digest.hexdigest(),
        'zstdSha256': digest(output),
        'pythonVersion': platform.python_version(),
        'zstdVersion': '.'.join(map(str, zstd.zstd_version_info)),
        'compression': {key.name: value for key, value in options.items()},
    }, indent=2) + '\n')


if __name__ == '__main__':
    recompress(*sys.argv[1:])
