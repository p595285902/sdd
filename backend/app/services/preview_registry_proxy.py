import ipaddress
import os
import select
import socket
import socketserver
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

REGISTRIES = frozenset({"registry.npmjs.org", "pypi.org", "files.pythonhosted.org"})
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


class ProxyHandler(BaseHTTPRequestHandler):
    timeout = 10

    def do_CONNECT(self) -> None:
        target = urlsplit("//" + self.path)
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
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if not addresses or any(
                not ipaddress.ip_address(address[4][0]).is_global
                for address in addresses
            ):
                self.send_error(403)
                return
            with socket.socket(addresses[0][0], socket.SOCK_STREAM) as upstream:
                upstream.settimeout(10)
                upstream.connect(addresses[0][4])
                self.send_response(200, "Connection established")
                self.end_headers()
                hello = self.connection.recv(MAX_HELLO)
                if server_name(hello) != host:
                    return
                upstream.sendall(hello)
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