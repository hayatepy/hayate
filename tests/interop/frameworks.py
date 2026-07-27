"""Real Django and FastAPI applications mounted beside Hayate."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from hayate import Context, Hayate, Response
from hayate.adapters import ASGIApplication, ASGIPathDispatcher

type Receive = Callable[[], Awaitable[dict[str, Any]]]
type Send = Callable[[dict[str, Any]], Awaitable[None]]


async def _request(application: ASGIApplication, path: str) -> tuple[int, bytes]:
    messages: list[dict[str, Any]] = []
    inbox = [{"type": "http.request", "body": b"", "more_body": False}]

    async def receive() -> dict[str, Any]:
        if inbox:
            return inbox.pop(0)
        # Django watches for disconnect concurrently while rendering. A real
        # server blocks here until the client actually goes away.
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.5"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 1234),
    }
    await application(scope, receive, send)
    status = next(
        message["status"] for message in messages if message["type"] == "http.response.start"
    )
    body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return status, body


def _hayate_application() -> Hayate:
    app = Hayate()

    @app.get("/api/health")
    async def health(c: Context) -> Response:
        return c.json({"framework": "hayate"})

    return app


async def test_real_fastapi_application_mount() -> None:
    from fastapi import FastAPI

    legacy = FastAPI()

    @legacy.get("/health")
    async def legacy_health() -> dict[str, str]:
        return {"framework": "fastapi"}

    application = ASGIPathDispatcher(
        _hayate_application(),
        {"/legacy-api": legacy},
    )

    assert await _request(application, "/api/health") == (
        200,
        b'{"framework":"hayate"}',
    )
    assert await _request(application, "/legacy-api/health") == (
        200,
        b'{"framework":"fastapi"}',
    )
    openapi_status, openapi_body = await _request(application, "/legacy-api/openapi.json")
    assert openapi_status == 200
    assert b'"/health"' in openapi_body


async def test_real_django_admin_mount() -> None:
    from django.conf import settings

    if not settings.configured:
        settings.configure(
            SECRET_KEY="interop-only-secret",
            ALLOWED_HOSTS=["testserver"],
            ROOT_URLCONF=__name__,
            INSTALLED_APPS=[
                "django.contrib.admin",
                "django.contrib.auth",
                "django.contrib.contenttypes",
                "django.contrib.messages",
                "django.contrib.sessions",
                "django.contrib.staticfiles",
            ],
            MIDDLEWARE=[
                "django.middleware.security.SecurityMiddleware",
                "django.contrib.sessions.middleware.SessionMiddleware",
                "django.middleware.common.CommonMiddleware",
                "django.middleware.csrf.CsrfViewMiddleware",
                "django.contrib.auth.middleware.AuthenticationMiddleware",
                "django.contrib.messages.middleware.MessageMiddleware",
            ],
            TEMPLATES=[
                {
                    "BACKEND": "django.template.backends.django.DjangoTemplates",
                    "APP_DIRS": True,
                    "OPTIONS": {
                        "context_processors": [
                            "django.template.context_processors.request",
                            "django.contrib.auth.context_processors.auth",
                            "django.contrib.messages.context_processors.messages",
                        ]
                    },
                }
            ],
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": ":memory:",
                }
            },
            STATIC_URL="/static/",
            USE_TZ=True,
        )

    import django

    django.setup()

    from django.contrib import admin
    from django.core.asgi import get_asgi_application
    from django.http import HttpRequest, JsonResponse
    from django.urls import path

    def scope_view(request: HttpRequest) -> JsonResponse:
        return JsonResponse(
            {
                "path_info": request.path_info,
                "script_name": request.META["SCRIPT_NAME"],
            }
        )

    global urlpatterns
    urlpatterns = [
        path("_scope/", scope_view),
        path("admin/", admin.site.urls),
    ]

    application = ASGIPathDispatcher(
        _hayate_application(),
        {"/legacy": get_asgi_application()},
    )

    assert await _request(application, "/api/health") == (
        200,
        b'{"framework":"hayate"}',
    )
    status, body = await _request(application, "/legacy/admin/login/")
    assert status == 200
    assert b"Django administration" in body

    status, body = await _request(application, "/legacy/_scope/")
    assert status == 200
    assert json.loads(body) == {
        "path_info": "/_scope/",
        "script_name": "/legacy",
    }
