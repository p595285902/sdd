import json
import signal
import sys
import time

mode = sys.argv[1]

if mode == "events":
    sys.stdout.write(json.dumps({"type": "text", "part": {"text": "complete"}}))
    sys.stdout.write("\n")
    sys.stdout.flush()
elif mode == "malformed":
    sys.stdout.write("not-json\n")
    sys.stdout.flush()
elif mode == "failure":
    sys.stderr.write("provider-secret failure\n")
    sys.stderr.flush()
    raise SystemExit(3)
elif mode == "opencode-server":
    import base64
    import os
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    port = int(sys.argv[2])
    prompted = threading.Event()
    permitted = threading.Event()
    authorized = "Basic " + base64.b64encode(
        ("opencode:" + os.environ["OPENCODE_SERVER_PASSWORD"]).encode()
    ).decode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, value):
            if self.headers.get("Authorization") != authorized:
                self.send_error(401)
                return False
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())
            return True

        def do_GET(self):
            if self.path.startswith("/global/health"):
                self.respond({"healthy": True})
            elif self.path.startswith("/session/ses_fixture"):
                self.respond({"id": "ses_fixture", "directory": os.getcwd()})
            elif self.path.startswith("/event"):
                if self.headers.get("Authorization") != authorized:
                    self.send_error(401)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.flush()
                prompted.wait()
                def emit(kind, **properties):
                    event = {"type": kind, "properties": {"sessionID": "ses_fixture", **properties}}
                    self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                    self.wfile.flush()
                emit("message.updated", info={"id": "msg_assistant", "role": "assistant"})
                emit("message.part.updated", part={"id": "part_text", "messageID": "msg_assistant", "type": "text", "text": ""})
                emit("message.part.delta", partID="part_text", messageID="msg_assistant", field="text", delta="Partial ")
                emit("permission.asked", id="permission_fixture", permission="read")
                assert permitted.wait(2)
                time.sleep(0.1)
                emit("message.part.delta", partID="part_text", messageID="msg_assistant", field="text", delta="response")
                emit("message.part.updated", part={"id": "part_text", "messageID": "msg_assistant", "type": "text", "text": "Partial response", "time": {"end": 1}})
                emit("session.status", status={"type": "idle"})

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.startswith("/session?"):
                assert payload["permission"] == [
                    {"permission": name, "action": "deny", "pattern": "*"}
                    for name in ("question", "plan_enter", "plan_exit")
                ]
                self.respond({"id": "ses_fixture", "directory": os.getcwd()})
            elif self.path.startswith("/session/ses_fixture/prompt_async"):
                assert payload["model"] == {"providerID": "openai", "modelID": "test"}
                assert payload["parts"] == [{"type": "text", "text": '"/openspec explore inspect"'}]
                self.respond({})
                prompted.set()
            elif self.path.startswith("/permission/permission_fixture/reply"):
                assert payload == {"reply": "once"}
                self.respond({})
                permitted.set()
            else:
                self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    sys.stdout.write(f"opencode server listening on http://127.0.0.1:{port}\n")
    sys.stdout.flush()
    server.serve_forever()

elif mode == "block":
    while True:
        time.sleep(0.05)
elif mode == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(0.05)
else:
    raise SystemExit(f"Unknown mode: {mode}")
