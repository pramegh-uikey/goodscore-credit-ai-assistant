"""Serve actual static files and FastAPI handlers through Playwright's transport.

No shared ports, running servers, provider credentials or changes to config.js.
Only the model boundary is stubbed by the tests that require deterministic text.
"""
import mimetypes
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "embedded-agent-be"))

from fastapi.testclient import TestClient
import server


def attach(page, frontend, api):
    client = TestClient(server.app)
    def backend(route):
        request = route.request
        suffix = request.url[len(api):]
        response = client.request(request.method, suffix, content=request.post_data,
                                  headers={"Content-Type": "application/json"})
        route.fulfill(status=response.status_code, body=response.content,
                      content_type="application/json", headers={"Access-Control-Allow-Origin": "*"})

    def static(route):
        path = urlparse(route.request.url).path
        if path == "/config.js":
            route.fulfill(body=f'const API_BASE = "{api}";', content_type="application/javascript")
            return
        path = path.strip("/") or "index.html"
        if "." not in Path(path).name:
            path += ".html"
        root = (ROOT / "embedded-agent-fe").resolve()
        file = (root / path).resolve()
        if root not in file.parents or not file.is_file():
            route.fulfill(status=404, body="Not found")
            return
        route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file)[0] or "text/plain")

    page.route(frontend.rstrip("/") + "/**", static)
    page.route(api.rstrip("/") + "/**", backend)
    return client
