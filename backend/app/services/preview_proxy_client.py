import select
import socket
import socketserver

SOCKET_PATH = "/registry-socket/proxy.sock"


class Forwarder(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        with socket.socket(socket.AF_UNIX) as upstream:
            upstream.settimeout(10)
            upstream.connect(SOCKET_PATH)
            sockets = (self.request, upstream)
            while True:
                readable, _, _ = select.select(sockets, [], [], 30)
                if not readable:
                    return
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.request else self.request).sendall(data)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("127.0.0.1", 3128), Forwarder) as server:
        server.serve_forever()