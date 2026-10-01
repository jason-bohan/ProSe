"""In-process HTTP server emulating the CFPB / RECAP / FTC endpoints.

Stands in for a dedicated mock-server tool (WireMock/Mockoon) so
``prose.crawler`` can be exercised over a real socket -- real URL encoding,
real gzip decompression, real timeouts, real malformed-response handling --
without adding a non-stdlib dependency or touching the live internet.

Usage::

    with MockRegulatoryServer({"/cfpb": Route(body=json.dumps(payload).encode())}) as server:
        monkeypatch.setattr(crawler, "CFPB_API_URL", f"{server.url}/cfpb")
        violations = CfpbSource().fetch()
"""

from __future__ import annotations

import gzip as gzip_module
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class Route:
    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    gzip_encode: bool = False
    delay: float = 0.0


@dataclass
class RecordedRequest:
    method: str
    path: str
    headers: dict[str, str]


class MockRegulatoryServer:
    """A local HTTP server serving canned responses keyed by path (ignoring query string)."""

    def __init__(self, routes: dict[str, Route] | None = None) -> None:
        self.routes: dict[str, Route] = dict(routes or {})
        self.requests: list[RecordedRequest] = []
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def set_route(self, path: str, route: Route) -> None:
        self.routes[path] = route

    @property
    def url(self) -> str:
        assert self._httpd is not None, "server not started"
        host, port = self._httpd.server_address[:2]
        return f"http://127.0.0.1:{port}"

    def __enter__(self) -> MockRegulatoryServer:
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: object) -> None:  # silence stdout
                return

            def do_GET(self) -> None:  # noqa: N802
                path = self.path.partition("?")[0]
                with server._lock:
                    server.requests.append(
                        RecordedRequest(method="GET", path=self.path, headers=dict(self.headers))
                    )
                route = server.routes.get(path)
                if route is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if route.delay:
                    import time

                    time.sleep(route.delay)
                body = route.body
                headers = dict(route.headers)
                if route.gzip_encode:
                    body = gzip_module.compress(body)
                    headers["Content-Encoding"] = "gzip"
                self.send_response(route.status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        assert self._httpd is not None
        self._httpd.shutdown()
        self._httpd.server_close()
        assert self._thread is not None
        self._thread.join(timeout=5)
