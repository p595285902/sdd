import ipaddress
import logging
import os
import select
import socket
import socketserver
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

# Explicit public registries/CDNs only. CONNECT, SNI and globally-routable DNS
# checks below apply equally to native Docker pulls and package installation.
REGISTRIES = frozenset({
    "registry.npmjs.org", "pypi.org", "files.pythonhosted.org",
    "registry-1.docker.io", "auth.docker.io",
    "production.cloudflare.docker.com", "production.cloudfront.docker.com",
    "docker-images-prod.6aa30f8b08e16409b46e0173d6de2f56.r2.cloudflarestorage.com",
})
MAX_HELLO = 8192
SOCKET_PATH = "/registry-socket/proxy.sock"


def server_name(hello: bytes) -> str | None:
    if len(hello) < 9 or hello[0] != 22:
        return None
    record_size = int.from_bytes(hello[3:5])
    if len(hello) < record_size + 5 or hello[5] != 1:
        return None
    data = memoryview(hello)[9 : 5 + record_size]
    if len(data) < 35:
        return None
    offset = 34
    for length_bytes in (1, 2, 1):
        if len(data) < offset + length_bytes:
            return None
        size = int.from_bytes(data[offset : offset + length_bytes])
        offset += length_bytes + size
    if len(data) < offset + 2:
        return None
    extensions = data[offset + 2 : offset + 2 + int.from_bytes(data[offset : offset + 2])]
    offset = 0
    while offset + 4 <= len(extensions):
        kind = int.from_bytes(extensions[offset : offset + 2])
        length = int.from_bytes(extensions[offset + 2 : offset + 4])
        value = extensions[offset + 4 : offset + 4 + length]
        if len(value) != length:
            return None
        if kind == 0 and len(value) >= 5 and value[2] == 0:
            name_size = int.from_bytes(value[3:5])
            if len(value) == 5 + name_size:
                try:
                    return bytes(value[5:]).decode("ascii").lower()
                except UnicodeError:
                    return None
        offset += 4 + length
    return None


def read_client_hello(connection: socket.socket) -> bytes:
    # Socket reads are not TLS record boundaries, including over the trusted
    # Unix-socket forwarder. Keep both the existing size bound and a total
    # deadline so fragmentation cannot turn into an unbounded slow read.
    hello = bytearray()
    deadline = time.monotonic() + 10
    previous_timeout = connection.gettimeout()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('TLS ClientHello deadline exceeded')
            connection.settimeout(remaining)
            chunk = connection.recv(MAX_HELLO - len(hello))
            if not chunk:
                raise ValueError('Incomplete TLS ClientHello')
            hello.extend(chunk)
            if len(hello) >= 5:
                record_size = 5 + int.from_bytes(hello[3:5])
                if record_size > MAX_HELLO:
                    raise ValueError('TLS ClientHello exceeds its size bound')
                if len(hello) >= record_size:
                    return bytes(hello)
    finally:
        connection.settimeout(previous_timeout)


def connect_registry(addresses: list[tuple]) -> socket.socket:
    # All addresses have already passed the public-address check. Pin each
    # attempt to that validated result, without resolving the hostname again.
    # Reserve time for remaining endpoints within one existing connect budget.
    deadline = time.monotonic() + 10
    for index, address in enumerate(addresses):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        upstream = socket.socket(address[0], socket.SOCK_STREAM)
        try:
            upstream.settimeout(remaining / (len(addresses) - index))
            upstream.connect(address[4])
            upstream.settimeout(10)
            return upstream
        except OSError:
            upstream.close()
    raise OSError('Public registry endpoints were unavailable within the connection budget')


class ProxyHandler(BaseHTTPRequestHandler):
    timeout = 10

    def do_CONNECT(self) -> None:
        target = urlsplit("//" + self.path)
        phase = "target validation"
        try:
            host = target.hostname
            if (
                host not in REGISTRIES
                or target.port != 443
                or target.username is not None
                or target.password is not None
            ):
                self.send_error(403)
                return
            phase = "public DNS resolution"
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if not addresses or any(
                not ipaddress.ip_address(address[4][0]).is_global
                for address in addresses
            ):
                self.send_error(403)
                return
            phase = "registry connection"
            with connect_registry(addresses) as upstream:
                self.send_response(200, "Connection established")
                self.end_headers()
                phase = "TLS ClientHello"
                hello = read_client_hello(self.connection)
                if server_name(hello) != host:
                    logging.getLogger(__name__).warning("Preview acquisition rejected TLS server name")
                    return
                upstream.sendall(hello)
                phase = "registry tunnel"
                sockets = (self.connection, upstream)
                while True:
                    readable, _, _ = select.select(sockets, [], [], 30)
                    if not readable:
                        break
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        (upstream if source is self.connection else self.connection).sendall(data)
        except (OSError, ValueError):
            # Fixed phase names only: never log project-controlled bytes,
            # credentials, exception contents or resolved addresses.
            logging.getLogger(__name__).warning("Preview acquisition failed during %s", phase)
            return

    def do_GET(self) -> None:
        self.send_error(403)

    do_POST = do_GET

    def log_message(self, format: str, *args: object) -> None:
        pass


class ProxyServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


if __name__ == "__main__":
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    with ProxyServer(SOCKET_PATH, ProxyHandler) as server:
        os.chmod(SOCKET_PATH, 0o666)
        server.serve_forever()
