"""A minimal local HTTP server that stands in for a git server's REST API.

``git-bot-feedback`` uses a Rust HTTP client, so Python-level HTTP mocking libraries
(like ``requests-mock``) can't intercept its requests. Instead, tests point
``GITHUB_API_URL`` at an instance of this server.
"""

from dataclasses import dataclass, field
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit


@dataclass
class RecordedRequest:
    """A request received by the `MockServer`."""

    method: str
    path: str  #: the URL path (without the query string)
    query: str
    headers: dict[str, str]
    body: bytes

    @property
    def url(self) -> str:
        return self.path + (f"?{self.query}" if self.query else "")

    def json(self) -> Any:
        return json.loads(self.body)


@dataclass
class _Route:
    method: str
    path: str
    status: int
    body: bytes
    headers: dict[str, str]
    accept: str | None = None
    query: str | None = None


@dataclass
class MockServer:
    """Routes are matched in reverse order of registration (latest wins)."""

    routes: list[_Route] = field(default_factory=list)
    requests: list[RecordedRequest] = field(default_factory=list)
    base_url: str = ""

    def add(
        self,
        method: str,
        path: str,
        text: str | bytes = "",
        status: int = 200,
        headers: dict[str, str] | None = None,
        accept: str | None = None,
        query: str | None = None,
    ):
        """Register a response.

        :param path: The URL path (starting with ``/``).
        :param accept: Only match requests whose ``Accept`` header contains this.
        :param query: Only match requests with exactly this query string.
            If `None`, then any query string matches.
        """
        body = text.encode("utf-8") if isinstance(text, str) else text
        self.routes.append(
            _Route(method.upper(), path, status, body, headers or {}, accept, query)
        )

    def get(self, path: str, **kwargs):
        self.add("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        self.add("POST", path, **kwargs)

    def patch(self, path: str, **kwargs):
        self.add("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs):
        self.add("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs):
        self.add("DELETE", path, **kwargs)

    def requests_to(self, method: str, path: str | None = None):
        return [
            r
            for r in self.requests
            if r.method == method.upper() and (path is None or r.path == path)
        ]

    def _find(self, req: RecordedRequest) -> _Route | None:
        for route in reversed(self.routes):
            if route.method != req.method or route.path != req.path:
                continue
            if route.query is not None and route.query != req.query:
                continue
            if route.accept is not None and route.accept not in req.headers.get(
                "accept", ""
            ):
                continue
            return route
        return None


def make_handler(server: MockServer):
    class Handler(BaseHTTPRequestHandler):
        def _handle(self):
            parts = urlsplit(self.path)
            length = int(self.headers.get("Content-Length", 0) or 0)
            req = RecordedRequest(
                method=self.command,
                path=parts.path,
                query=parts.query,
                headers={k.lower(): v for k, v in self.headers.items()},
                body=self.rfile.read(length) if length else b"",
            )
            server.requests.append(req)
            route = server._find(req)
            if route is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(route.status)
            for key, value in route.headers.items():
                self.send_header(key, value.replace("{base_url}", server.base_url))
            self.send_header("Content-Length", str(len(route.body)))
            self.end_headers()
            self.wfile.write(route.body)

        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _handle  # noqa: N815

        def log_message(self, format, *args):  # silence stderr noise
            pass

    return Handler


def start_mock_server() -> tuple[MockServer, ThreadingHTTPServer]:
    server = MockServer()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(server))
    server.base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return server, httpd


def diff_to_pr_files(diff: str) -> str:
    """Convert a unified git diff into the JSON returned by the REST API's
    "list pull request files" endpoint."""
    files = []
    for chunk in re.split(r"^diff --git ", diff, flags=re.MULTILINE)[1:]:
        name = re.search(r"^\+\+\+ b/(.+)$", chunk, flags=re.MULTILINE)
        start = chunk.find("\n@@")
        if name is None or start < 0:
            continue
        patch = chunk[start + 1 :].rstrip("\n")
        changes = sum(
            1
            for line in patch.splitlines()
            if line[:1] in "+-" and not line.startswith(("+++", "---"))
        )
        files.append(
            {
                "filename": name.group(1),
                "status": "modified",
                "changes": changes,
                "patch": patch,
            }
        )
    return json.dumps(files)
