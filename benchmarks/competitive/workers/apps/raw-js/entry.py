"""Python dispatch with direct JS Request/Response access.

This control isolates the cost of workers-py's ergonomic wrappers from the
unavoidable Python entrypoint and Pyodide FFI boundary.
"""

import json

import js
from pyodide.ffi import to_js
from workers import WorkerEntrypoint


def _options(headers, *, status=200):
    return to_js(
        {"headers": headers, "status": status},
        dict_converter=js.Object.fromEntries,
    )


def _headers(*pairs):
    headers = js.Headers.new()
    for name, value in pairs:
        headers.append(name, value)
    return headers


TEXT_HEADERS = _headers(("content-type", "text/plain; charset=UTF-8"))
JSON_HEADERS = _headers(("content-type", "application/json"))
TEXT_OPTIONS = _options(TEXT_HEADERS)
JSON_OPTIONS = _options(JSON_HEADERS)
METHOD_OPTIONS = _options(
    _headers(
        ("allow", "GET, HEAD"),
        ("content-type", "text/plain; charset=UTF-8"),
    ),
    status=405,
)
NOT_FOUND_OPTIONS = _options(TEXT_HEADERS, status=404)


def _pathname(url):
    scheme_end = url.find("://")
    path_start = url.find("/", scheme_end + 3)
    if path_start < 0:
        return "/"
    query_start = url.find("?", path_start)
    return url[path_start:] if query_start < 0 else url[path_start:query_start]


class Default(WorkerEntrypoint):
    def fetch(self, request):
        raw = request.js_object
        method = str(raw.method)
        path = _pathname(str(raw.url))
        if method == "HEAD" and path == "/text":
            return js.Response.new(None, TEXT_OPTIONS)
        if method == "GET" and path == "/text":
            return js.Response.new("hello", TEXT_OPTIONS)
        if method == "GET" and path.startswith("/items/"):
            item_id = path[7:]
            return js.Response.new(
                f'{{"id":"{item_id}","name":"item-{item_id}"}}',
                JSON_OPTIONS,
            )
        if method == "POST" and path == "/echo":
            return self._echo(raw)
        if method == "GET" and path.startswith("/route"):
            route, separator, _key = path[6:].partition("/")
            if separator and route.isdigit() and 0 <= int(route) < 64:
                return js.Response.new("ok", TEXT_OPTIONS)
        if path == "/text":
            return js.Response.new("Method Not Allowed", METHOD_OPTIONS)
        return js.Response.new("Not Found", NOT_FOUND_OPTIONS)

    async def _echo(self, raw):
        data = json.loads(await raw.text())
        message = data["message"]
        return js.Response.new(
            json.dumps(
                {"message": message, "length": len(message)},
                separators=(",", ":"),
            ),
            JSON_OPTIONS,
        )
