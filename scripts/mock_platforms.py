"""Tiny fake of Mastodon / Bluesky / Discord APIs for an end-to-end run over real HTTP."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE = "http://127.0.0.1:4100"

class H(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        auth = self.headers.get("Authorization", "")
        if self.path == "/api/v1/statuses":
            if auth != "Bearer good-mastodon":
                return self._send(401, {"error": "The access token is invalid"})
            return self._send(200, {"url": f"{BASE}/@me/1", "visibility": body["visibility"]})
        if self.path.endswith("createSession"):
            return self._send(200, {"accessJwt": "jwt", "did": "did:plc:x", "handle": "me.test"})
        if self.path.endswith("createRecord"):
            assert body["record"]["facets"], "link facet missing"
            return self._send(200, {"uri": "at://did:plc:x/app.bsky.feed.post/3abc"})
        if self.path.startswith("/api/webhooks/1/tok"):
            return self._send(200, {"id": "111", "channel_id": "222"})
        self._send(404, {"message": "not found"})

    def do_GET(self):
        if self.path == "/api/webhooks/1/tok":
            return self._send(200, {"guild_id": "333"})
        if self.path == "/@me/1":
            return self._send(200, {"ok": True})
        self._send(404, {"message": "not found"})

    def log_message(self, *a): pass

HTTPServer(("127.0.0.1", 4100), H).serve_forever()
