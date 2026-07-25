"""The common competitive workload implemented with Django."""

import json

import django
from django.conf import settings
from django.core.asgi import get_asgi_application
from django.http import HttpResponse, JsonResponse
from django.urls import path
from django.views.decorators.http import require_GET, require_POST

settings.configure(
    ALLOWED_HOSTS=["*"],
    DEBUG=False,
    MIDDLEWARE=[],
    ROOT_URLCONF=__name__,
    SECRET_KEY="benchmark-only",
)

django.setup()

_COMPACT_JSON = {"separators": (",", ":")}


@require_GET
async def text(request):
    return HttpResponse("hello", content_type="text/plain; charset=utf-8")


@require_GET
async def item(request, item_id: str):
    return JsonResponse(
        {"id": item_id, "name": f"item-{item_id}"},
        json_dumps_params=_COMPACT_JSON,
    )


@require_POST
async def echo(request):
    data = json.loads(request.body)
    message = data["message"]
    return JsonResponse(
        {"message": message, "length": len(message)},
        json_dumps_params=_COMPACT_JSON,
    )


@require_GET
async def route(request, key: str):
    return HttpResponse("ok", content_type="text/plain; charset=utf-8")


urlpatterns = [
    path("text", text),
    path("items/<str:item_id>", item),
    path("echo", echo),
    *(path(f"route{index}/<str:key>", route) for index in range(64)),
]

application = get_asgi_application()
