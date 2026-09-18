"""Explicit immutable native project/preparation snapshots over an HTTP CAS.

The endpoint and pinned digest are trusted build inputs. This is not a Bazel
Action Cache protocol or a mutable latest-snapshot service.
"""
import json
import re

from portable_cache import fetch, put, sha, publish, valid_path

POLICY = 'native-remote-snapshot-v1'


def valid_digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def validate(value):
    if not isinstance(value, dict) or set(value) != {'policy', 'projects', 'preparation'} or value['policy'] != POLICY:
        raise ValueError('invalid remote snapshot')
    if value['preparation'] is not None and not valid_digest(value['preparation']): raise ValueError('invalid preparation digest')
    if not isinstance(value['projects'], list) or len(value['projects']) > 100000: raise ValueError('invalid project catalog')
    seen = set()
    for record in value['projects']:
        if (not isinstance(record, dict) or set(record) != {'key', 'project', 'inputs', 'toolchain', 'blob'} or
                not valid_path(record['project']) or any(not valid_digest(record[k]) for k in ('key', 'inputs', 'toolchain', 'blob')) or record['key'] in seen):
            raise ValueError('invalid project record')
        seen.add(record['key'])
    return value


def download(endpoint, key):
    if not valid_digest(key): raise ValueError('invalid snapshot digest')
    data = fetch(endpoint + '/cas/' + key)
    if len(data) > 64 * 1024 * 1024 or sha(data) != key: raise ValueError('snapshot digest mismatch')
    return validate(json.loads(data))


def upload(endpoint, folder, preparation=None, *, verified_blobs=()):
    publication = publish(endpoint, folder, verified_blobs=verified_blobs)
    if publication['errors']: raise OSError('project bundle publication failed: ' + str(publication['errors']))
    snapshot = validate(dict(policy=POLICY, projects=publication['entries'], preparation=preparation))
    data = json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()
    key = sha(data)
    put(endpoint + '/cas/' + key, data)
    return key
