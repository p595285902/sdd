import logging
import select
import socket
import socketserver
import threading
import time
from pathlib import Path

from preview_workspace_sync import sync_workspace

SOCKET_PATH = "/registry-socket/proxy.sock"
logger = logging.getLogger(__name__)


def keep_workspace_current(
    checkout: Path, workspace: Path, previous: dict[str, bytes]
) -> None:
    while True:
        time.sleep(1)
        try:
            previous = sync_workspace(checkout, workspace, previous)
        except OSError, RuntimeError:
            logger.exception("Preview workspace sync failed")
            continue


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
    checkout = Path("/checkout")
    workspace = Path("/workspace")
    previous = sync_workspace(checkout, workspace, {})
    Path("/tmp/preview-source-ready").touch()
    threading.Thread(
        target=keep_workspace_current, args=(checkout, workspace, previous), daemon=True
    ).start()
    with Server(("127.0.0.1", 3128), Forwarder) as server:
        server.serve_forever()
