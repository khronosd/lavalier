"""A loopback fake Ollama: records each request's path and JSON body, replies from a script."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOllama:
    def __init__(self, models=("m",), chat_content='{"summary": "A day."}', fail_status=None):
        self.models = list(models)
        self.chat_content = chat_content
        self.fail_status = fail_status
        self.headers: list[dict] = []
        self.requests: list[tuple[str, str, object]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n)) if n else None
                outer.headers.append(dict(self.headers))
                outer.requests.append((method, self.path, body))
                if outer.fail_status:
                    return self._send(outer.fail_status, b"boom " + b"x" * 500)
                if self.path == "/api/tags":
                    return self._send(200, {"models": [{"name": m} for m in outer.models]})
                if self.path == "/api/chat":
                    return self._send(200, {"message": {"role": "assistant", "content": outer.chat_content}})
                self._send(404, {"error": "no"})

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *a):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
