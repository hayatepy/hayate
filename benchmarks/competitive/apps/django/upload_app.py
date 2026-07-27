"""The competitive multipart upload workload implemented with Django."""

import hashlib

import django
from django.conf import settings
from django.core.asgi import get_asgi_application
from django.core.files.uploadedfile import TemporaryUploadedFile
from django.http import HttpResponse, JsonResponse
from django.urls import path
from django.views.decorators.http import require_GET, require_POST

settings.configure(
    ALLOWED_HOSTS=["*"],
    DATA_UPLOAD_MAX_MEMORY_SIZE=70 * 1024 * 1024,
    DEBUG=False,
    FILE_UPLOAD_MAX_MEMORY_SIZE=1024 * 1024,
    MIDDLEWARE=[],
    ROOT_URLCONF=__name__,
    SECRET_KEY="benchmark-only",
)

django.setup()
_COMPACT_JSON = {"separators": (",", ":")}


@require_GET
async def health(request):
    return HttpResponse("ok", content_type="text/plain; charset=utf-8")


@require_POST
async def upload(request):
    file = request.FILES.get("file")
    if file is None:
        return JsonResponse({"error": "file required"}, status=400)
    digest = hashlib.sha256()
    size = 0
    for chunk in file.chunks(chunk_size=64 * 1024):
        size += len(chunk)
        digest.update(chunk)
    return JsonResponse(
        {
            "size": size,
            "sha256": digest.hexdigest(),
            "temp_disk_bytes": size if isinstance(file, TemporaryUploadedFile) else 0,
        },
        json_dumps_params=_COMPACT_JSON,
    )


urlpatterns = [
    path("health", health),
    path("upload", upload),
]

application = get_asgi_application()
