"""Tiny local webhook receiver for testing dispatch end to end.

  python mock_receiver.py --port 8099 --secret test-secret [--fail-first 2]

Verifies the HMAC signature and appends accepted events to received.jsonl.
`--fail-first N` answers HTTP 503 to the first N requests so retry logic can be observed.
"""
import argparse, json
from http.server import BaseHTTPRequestHandler, HTTPServer
from dispatcher import verify_signature

p = argparse.ArgumentParser()
p.add_argument("--port", type=int, default=8099); p.add_argument("--secret", required=True)
p.add_argument("--fail-first", type=int, default=0); p.add_argument("--out", default="received.jsonl")
args = p.parse_args()
state = {"n": 0}

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        state["n"] += 1
        if state["n"] <= args.fail_first:
            self.send_response(503); self.end_headers(); return
        ok = verify_signature(args.secret, self.headers.get("X-Timestamp", ""), body, self.headers.get("X-Signature", ""))
        if not ok:
            self.send_response(401); self.end_headers(); return
        with open(args.out, "a") as f:
            f.write(json.dumps({"idempotency_key": self.headers.get("X-Idempotency-Key"), "event": json.loads(body)}) + "\n")
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass

print(f"listening on http://127.0.0.1:{args.port}", flush=True)
HTTPServer(("127.0.0.1", args.port), H).serve_forever()
