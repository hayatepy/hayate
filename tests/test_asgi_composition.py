"""Adapter-level composition with existing ASGI applications."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any

import pytest

from hayate.adapters.asgi import ASGIPathDispatcher

type Receive = Callable[[], Awaitable[dict[str, Any]]]
type Send = Callable[[dict[str, Any]], Awaitable[None]]


class RecordingApplication:
    def __init__(self, name: str) -> None:
        self.name = name
        self.scopes: list[dict[str, Any]] = []

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Receive,
        send: Send,
    ) -> None:
        self.scopes.append(scope)
        await send({"type": "selected", "application": self.name})


async def _dispatch(
    application: ASGIPathDispatcher,
    scope: dict[str, Any],
) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await application(scope, receive, send)
    return sent


def _scope(
    path: str,
    *,
    kind: str = "http",
    raw_path: bytes | None = None,
    root_path: str = "",
) -> dict[str, Any]:
    scope: dict[str, Any] = {
        "type": kind,
        "path": path,
        "root_path": root_path,
        "query_string": b"page=2",
        "headers": [(b"host", b"testserver")],
    }
    if raw_path is not None:
        scope["raw_path"] = raw_path
    return scope


async def test_exact_mount_rewrites_to_subapplication_root() -> None:
    root = RecordingApplication("root")
    admin = RecordingApplication("admin")
    application = ASGIPathDispatcher(root, {"/admin": admin})

    sent = await _dispatch(application, _scope("/admin", raw_path=b"/admin"))

    assert sent == [{"type": "selected", "application": "admin"}]
    assert admin.scopes[0]["path"] == "/"
    assert admin.scopes[0]["raw_path"] == b"/"
    assert admin.scopes[0]["root_path"] == "/admin"


async def test_mount_preserves_query_and_extends_existing_root_path() -> None:
    root = RecordingApplication("root")
    admin = RecordingApplication("admin")
    application = ASGIPathDispatcher(root, {"/admin": admin})
    scope = _scope(
        "/admin/users/1",
        raw_path=b"/admin/users%2F1",
        root_path="/proxy/",
    )
    original = deepcopy(scope)

    await _dispatch(application, scope)

    mounted = admin.scopes[0]
    assert mounted["path"] == "/users/1"
    assert mounted["raw_path"] == b"/users%2F1"
    assert mounted["root_path"] == "/proxy/admin"
    assert mounted["query_string"] == b"page=2"
    assert mounted["headers"] == [(b"host", b"testserver")]
    assert scope == original
    assert mounted is not scope


async def test_encoded_or_missing_raw_prefix_is_safely_omitted() -> None:
    root = RecordingApplication("root")
    mounted = RecordingApplication("mounted")
    application = ASGIPathDispatcher(root, {"/cafe": mounted})

    await _dispatch(application, _scope("/cafe/menu", raw_path=b"/%63afe/menu"))

    assert mounted.scopes[0]["path"] == "/menu"
    assert "raw_path" not in mounted.scopes[0]


async def test_prefix_match_requires_a_path_segment_boundary() -> None:
    root = RecordingApplication("root")
    admin = RecordingApplication("admin")
    application = ASGIPathDispatcher(root, {"/admin": admin})

    sent = await _dispatch(application, _scope("/administrator"))

    assert sent == [{"type": "selected", "application": "root"}]
    assert admin.scopes == []
    assert root.scopes[0]["path"] == "/administrator"


async def test_longest_prefix_wins_independent_of_mapping_order() -> None:
    root = RecordingApplication("root")
    api = RecordingApplication("api")
    internal = RecordingApplication("internal")
    application = ASGIPathDispatcher(
        root,
        {
            "/api": api,
            "/api/internal": internal,
        },
    )

    sent = await _dispatch(application, _scope("/api/internal/health"))

    assert sent == [{"type": "selected", "application": "internal"}]
    assert internal.scopes[0]["path"] == "/health"
    assert api.scopes == []


async def test_websocket_scopes_use_the_same_mount_contract() -> None:
    root = RecordingApplication("root")
    realtime = RecordingApplication("realtime")
    application = ASGIPathDispatcher(root, {"/legacy": realtime})

    sent = await _dispatch(
        application,
        _scope("/legacy/ws", kind="websocket", raw_path=b"/legacy/ws"),
    )

    assert sent == [{"type": "selected", "application": "realtime"}]
    assert realtime.scopes[0]["type"] == "websocket"
    assert realtime.scopes[0]["path"] == "/ws"
    assert realtime.scopes[0]["root_path"] == "/legacy"


@pytest.mark.parametrize("kind", ["lifespan", "custom"])
async def test_non_request_scopes_remain_owned_by_the_root(kind: str) -> None:
    root = RecordingApplication("root")
    mounted = RecordingApplication("mounted")
    application = ASGIPathDispatcher(root, {"/mounted": mounted})

    sent = await _dispatch(application, {"type": kind})

    assert sent == [{"type": "selected", "application": "root"}]
    assert root.scopes == [{"type": kind}]
    assert mounted.scopes == []


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("admin", "must start"),
        ("/", "cannot be '/'"),
        ("/admin/", "must not end"),
        ("/admin//users", "empty"),
        ("/admin/./users", "'.'"),
        ("/admin/../users", "'..'"),
        ("/管理", "ASCII"),
        ("/admin?next=/users", "unescaped ASCII"),
        ("/admin users", "unescaped ASCII"),
        ("/admin\\users", "unescaped ASCII"),
    ],
)
def test_invalid_mount_paths_fail_eagerly(path: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ASGIPathDispatcher(RecordingApplication("root"), {path: RecordingApplication("mounted")})


def test_non_callable_applications_fail_eagerly() -> None:
    with pytest.raises(TypeError, match="default"):
        ASGIPathDispatcher(None, {})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="/mounted"):
        ASGIPathDispatcher(  # type: ignore[dict-item]
            RecordingApplication("root"),
            {"/mounted": None},
        )
