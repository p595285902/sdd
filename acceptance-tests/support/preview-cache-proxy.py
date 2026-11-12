"""Acceptance-only Docker Hub cache adapter; not part of production images.

The private daemon addresses a synthetic mirror through its existing bounded
Unix-socket acquisition transport. Only this trusted helper knows the real
cache address. Other public acquisition retains the production proxy policy.
"""
import http.client
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from preview_public_registry_proxy import ProxyHandler, ProxyServer, SOCKET_PATH

MIRROR = "acceptance-cache.invalid"
CONFIG = Path("/controller/acceptance-cache-upstream")
UPSTREAM = urlsplit(CONFIG.read_text().strip() if CONFIG.exists() else "")
HUB = frozenset({"registry-1.docker.io", "auth.docker.io"})
REQUEST_HEADERS = ("Accept", "Accept-Encoding", "Range", "If-Range", "If-None-Match", "If-Modified-Since", "User-Agent")
RESPONSE_HEADERS = frozenset({
    "content-type", "content-length", "content-encoding", "docker-content-digest",
    "docker-distribution-api-version", "etag", "last-modified", "accept-ranges",
    "content-range", "cache-control",
})


def registry_path(target):
    if target.fragment or target.query not in ("", "ns=docker.io"):
        return False
    if target.path == "/v2/":
        return True
    return bool(re.fullmatch(
        r"/v2/[a-z0-9][a-z0-9._/-]*/(?:manifests|blobs)/[A-Za-z0-9_][A-Za-z0-9_.:+-]*",
        target.path,
    )) and all(part not in ("", ".", "..") for part in target.path.split("/")[2:])


class CacheProxyHandler(ProxyHandler):
    def do_CONNECT(self):
        target = urlsplit("//" + self.path)
        if target.hostname in HUB or target.hostname == MIRROR:
            # Docker normally falls back to Hub after a mirror failure. Do not
            # silently bypass the operator's cache or consume anonymous quota.
            self.send_error(403, "Acceptance Docker Hub acquisition requires its configured cache")
            return
        super().do_CONNECT()

    def mirror_request(self):
        target = urlsplit(self.path)
        if (len(self.path) > 4096 or target.scheme != "http" or target.netloc != MIRROR
                or target.username or target.password or not registry_path(target)):
            self.send_error(403)
            return
        if (UPSTREAM.scheme not in ("http", "https") or not UPSTREAM.hostname
                or UPSTREAM.username or UPSTREAM.password or UPSTREAM.path not in ("", "/")
                or UPSTREAM.query or UPSTREAM.fragment):
            self.send_error(503, "Acceptance Docker cache is not configured")
            return
        connection_type = http.client.HTTPSConnection if UPSTREAM.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(UPSTREAM.hostname, UPSTREAM.port, timeout=10)
        started = False
        try:
            # Do not forward credentials, cookies, arbitrary destinations or
            # hop-by-hop headers from a project to the host's cache service.
            headers = {name: self.headers[name] for name in REQUEST_HEADERS if name in self.headers}
            # Docker sends separate Accept fields for Docker and OCI formats.
            # Reading only the first makes cached OCI manifests look missing.
            if accepts := self.headers.get_all("Accept"):
                headers["Accept"] = ", ".join(accepts)
            connection.request(self.command, target.path + ("?" + target.query if target.query else ""), headers=headers)
            response = connection.getresponse()
            if 300 <= response.status < 400 and response.status != 304:
                self.send_error(502, "Acceptance cache must serve registry content without redirects")
                return
            self.send_response(response.status)
            for name, value in response.getheaders():
                if name.lower() in RESPONSE_HEADERS:
                    self.send_header(name, value)
            self.end_headers()
            started = True
            if self.command != "HEAD":
                while chunk := response.read(65536):
                    self.wfile.write(chunk)
        except (OSError, ValueError, http.client.HTTPException):
            if not started:
                self.send_error(502, "Acceptance Docker cache is unavailable")
            self.close_connection = True
        finally:
            connection.close()

    do_GET = mirror_request
    do_HEAD = mirror_request
    # Retain the production rejection of POST, including registry writes.


if __name__ == "__main__":
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    with ProxyServer(SOCKET_PATH, CacheProxyHandler) as server:
        os.chmod(SOCKET_PATH, 0o666)
        server.serve_forever()
