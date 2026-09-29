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
elif mode == "block":
    while True:
        time.sleep(0.05)
elif mode == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(0.05)
else:
    raise SystemExit(f"Unknown mode: {mode}")
