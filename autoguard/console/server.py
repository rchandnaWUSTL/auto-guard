"""Live decision console: serves one page and streams the decision log over SSE."""

import json
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import log as _log

HERE = Path(__file__).parent
SCENES = Path.cwd() / "demo" / "scenes"


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            body = (HERE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path.startswith("/scenes/"):
            scene = SCENES / Path(path).name
            if scene.suffix == ".json" and scene.is_file():
                self.send_json(json.loads(scene.read_text()))
            else:
                self.send_json({"error": "no scene %s; run autoguard demo --record" % scene.name}, 404)
        elif path == "/events":
            self.stream()
        else:
            self.send_error(404)

    def stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        log = _log.log_path()
        pos = log.stat().st_size if log.is_file() else 0
        # Replay the last few decisions so the page isn't empty on load.
        if log.is_file():
            for line in log.read_text().splitlines()[-8:]:
                self.wfile.write(b"data: " + line.encode() + b"\n\n")
            self.wfile.flush()
        idle = 0
        try:
            while True:
                if log.is_file() and log.stat().st_size > pos:
                    with log.open() as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    for line in chunk.splitlines():
                        if line.strip():
                            self.wfile.write(b"data: " + line.encode() + b"\n\n")
                    self.wfile.flush()
                    idle = 0
                else:
                    idle += 1
                    if idle % 50 == 0:  # keep-alive every ~5s
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError):
            pass


def serve(port=8787):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    print("Auto-Guard console: http://127.0.0.1:%d  (log: %s)" % (port, _log.log_path()))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
