import hashlib
from pathlib import Path
import sys
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from probe_http_cache import CacheServer

class HttpCache(unittest.TestCase):
    def test_content_addressing_namespace_and_outage(self):
        with CacheServer() as cache:
            data=b'owned artifact';key=hashlib.sha256(data).hexdigest()
            native=cache.url+'/native/cas/'+key
            with urlopen(Request(native,data=data,method='PUT')) as r:self.assertEqual(r.status,200)
            with urlopen(native) as r:self.assertEqual(r.read(),data)
            with self.assertRaises(HTTPError) as e:urlopen(Request(native,data=b'wrong',method='PUT'))
            self.assertEqual(e.exception.code,400)
            with urlopen(native) as r:self.assertEqual(r.read(),data)
            with self.assertRaises(HTTPError) as e:urlopen(cache.url+'/bazel/cas/'+key)
            self.assertEqual(e.exception.code,404)
            cache.offline=True
            with self.assertRaises(HTTPError) as e:urlopen(native)
            self.assertEqual(e.exception.code,503)
            self.assertEqual(cache.totals()['errors'],1)

if __name__=='__main__':unittest.main()
