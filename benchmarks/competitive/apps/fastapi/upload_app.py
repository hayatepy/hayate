"""The competitive multipart upload workload implemented with FastAPI."""

import hashlib
from typing import Annotated

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)


@app.get("/health", response_class=PlainTextResponse)
async def health():
    return PlainTextResponse("ok")


@app.post("/upload", response_class=JSONResponse)
async def upload(file: Annotated[UploadFile, File()]):
    digest = hashlib.sha256()
    size = 0
    while chunk := await file.read(64 * 1024):
        size += len(chunk)
        digest.update(chunk)
    spooled = bool(getattr(file.file, "_rolled", False))
    return JSONResponse(
        {
            "size": size,
            "sha256": digest.hexdigest(),
            "temp_disk_bytes": size if spooled else 0,
        }
    )
