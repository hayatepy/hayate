"""The common workload using only the official Python Workers SDK."""

import json
from urllib.parse import urlsplit

from workers import Response, WorkerEntrypoint

JSON_HEADERS = {"content-type": "application/json"}
TEXT_HEADERS = {"content-type": "text/plain; charset=UTF-8"}


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        method_value = request.method
        method = str(getattr(method_value, "value", method_value))
        path = urlsplit(request.url).path
        if method == "HEAD" and path == "/text":
            return Response(None, headers=TEXT_HEADERS)
        if method == "GET" and path == "/text":
            return Response(b"hello", headers=TEXT_HEADERS)
        if method == "GET" and path.startswith("/items/"):
            item_id = path.removeprefix("/items/")
            return Response(
                json.dumps({"id": item_id, "name": f"item-{item_id}"}, separators=(",", ":")),
                headers=JSON_HEADERS,
            )
        if method == "POST" and path == "/echo":
            data = await request.json()
            message = data["message"]
            return Response(
                json.dumps({"message": message, "length": len(message)}, separators=(",", ":")),
                headers=JSON_HEADERS,
            )
        if method == "GET" and path.startswith("/route"):
            route, separator, _key = path.removeprefix("/route").partition("/")
            if separator and route.isdigit() and 0 <= int(route) < 64:
                return Response(b"ok", headers=TEXT_HEADERS)
        if path == "/text":
            return Response(
                "Method Not Allowed",
                status=405,
                headers={"allow": "GET, HEAD", **TEXT_HEADERS},
            )
        return Response("Not Found", status=404, headers=TEXT_HEADERS)
