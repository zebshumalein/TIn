"""Serve the frontend on all interfaces at port 5500 and proxy to port 8000."""
from http.client import HTTPConnection, HTTPException
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    PUBLIC_FILES = {"/", "/index.html", "/app.js", "/styles.css", "/soft-aurora.js"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/api/") or path == "/openapi.json":
            self._proxy_api()
        elif path in self.PUBLIC_FILES:
            self.path = path
            super().do_GET()
        else:
            self.send_error(404, "Not found")

    def do_POST(self):
        if urlsplit(self.path).path.startswith("/api/"):
            self._proxy_api()
        else:
            self.send_error(404, "Not found")

    def do_OPTIONS(self):
        if urlsplit(self.path).path.startswith("/api/"):
            self._proxy_api()
        else:
            self.send_error(404, "Not found")

    def _proxy_api(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "connection", "content-length"}
        }
        connection = HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=300)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in {"connection", "transfer-encoding", "content-length"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        except (OSError, HTTPException) as exc:
            self.send_error(502, f"Backend API is unavailable: {exc}")
        finally:
            connection.close()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 5500), Handler)
    print("Frontend listening on 0.0.0.0:5500; API requests proxy to 127.0.0.1:8000")
    server.serve_forever()
