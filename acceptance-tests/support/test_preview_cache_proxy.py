"""Local-only regression tests for the acceptance cache adapter."""
import http.client
import importlib.util
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


production = load("preview_public_registry_proxy", ROOT / "backend/app/services/preview_registry_proxy.py")
cache = load("acceptance_cache_proxy", Path(__file__).with_name("preview-cache-proxy.py"))


class CacheProxyTests(unittest.TestCase):
    def setUp(self):
        self.received = []
        self.status = 200
        owner = self

        class Registry(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.received.append((self.command, self.path, self.headers))
                self.send_response(owner.status)
                self.send_header("Content-Length", "6")
                self.send_header("Docker-Content-Digest", "sha256:test")
                self.end_headers()
                if self.command != "HEAD" and owner.status != 304:
                    self.wfile.write(b"cached")

            do_HEAD = do_GET

            def log_message(self, *_args):
                pass

        self.registry = ThreadingHTTPServer(("127.0.0.1", 0), Registry)
        self.proxy = ThreadingHTTPServer(("127.0.0.1", 0), cache.CacheProxyHandler)
        cache.UPSTREAM = urlsplit(f"http://127.0.0.1:{self.registry.server_port}")
        for server in (self.registry, self.proxy):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)

    def request(self, method="GET", target="http://acceptance-cache.invalid/v2/library/python/manifests/latest", **headers):
        connection = http.client.HTTPConnection("127.0.0.1", self.proxy.server_port, timeout=3)
        try:
            connection.request(method, target, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_reads_fixed_cache_and_strips_credentials(self):
        status, headers, body = self.request(Authorization="Bearer project-secret", Cookie="session=private", Accept="application/json")
        self.assertEqual((status, body), (200, b"cached"))
        self.assertEqual(headers["Docker-Content-Digest"], "sha256:test")
        method, target, forwarded = self.received[0]
        self.assertEqual((method, target), ("GET", "/v2/library/python/manifests/latest"))
        self.assertEqual(forwarded["Accept"], "application/json")
        self.assertIsNone(forwarded["Authorization"])
        self.assertIsNone(forwarded["Cookie"])

    def test_head_and_buildkit_namespace_use_same_cache(self):
        status, _, body = self.request("HEAD", "http://acceptance-cache.invalid/v2/library/python/blobs/sha256:abc?ns=docker.io")
        self.assertEqual((status, body), (200, b""))
        self.assertEqual(self.received[0][0], "HEAD")

    def test_arbitrary_host_paths_writes_and_direct_hub_are_rejected(self):
        for method, target in [
            ("GET", "http://host.docker.internal:5001/v2/"),
            ("GET", "http://acceptance-cache.invalid/admin"),
            ("GET", "http://acceptance-cache.invalid/v2/../admin/manifests/latest"),
            ("GET", "http://acceptance-cache.invalid/v2/library/python/manifests/latest?destination=private"),
            ("POST", "http://acceptance-cache.invalid/v2/library/python/blobs/uploads/"),
            ("CONNECT", "registry-1.docker.io:443"),
            ("CONNECT", "auth.docker.io:443"),
        ]:
            with self.subTest(method=method, target=target):
                self.assertEqual(self.request(method, target)[0], 403)
        self.assertEqual(self.received, [])

    def test_cache_error_is_not_a_direct_hub_fallback(self):
        self.status = 429
        self.assertEqual(self.request()[0], 429)
        self.assertEqual(len(self.received), 1)

    def test_redirects_cannot_escape_cache_and_not_modified_is_preserved(self):
        self.status = 302
        self.assertEqual(self.request()[0], 502)
        self.status = 304
        self.assertEqual(self.request()[0], 304)

    def test_other_connect_acquisition_keeps_production_handler(self):
        calls = []
        original = production.ProxyHandler.do_CONNECT
        production.ProxyHandler.do_CONNECT = lambda handler: (calls.append(handler.path), handler.send_error(403))
        try:
            self.assertEqual(self.request("CONNECT", "pypi.org:443")[0], 403)
            self.assertEqual(calls, ["pypi.org:443"])
        finally:
            production.ProxyHandler.do_CONNECT = original


if __name__ == "__main__":
    unittest.main()
