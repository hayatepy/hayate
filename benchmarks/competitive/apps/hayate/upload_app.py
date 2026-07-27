"""The competitive multipart upload workload implemented with Hayate."""

import hashlib

from hayate import Context, File, FormDataLimits, Hayate

app = Hayate()
_LIMITS = FormDataLimits(
    max_body_bytes=70 * 1024 * 1024,
    max_file_bytes=64 * 1024 * 1024,
    max_field_bytes=64 * 1024,
    max_parts=4,
    max_header_bytes=8 * 1024,
    file_memory_bytes=1024 * 1024,
)


@app.get("/health")
async def health(c: Context):
    return c.text("ok")


@app.post("/upload")
async def upload(c: Context):
    form = await c.req.form_data(_LIMITS)
    async with form:
        file = form.get("file")
        if not isinstance(file, File):
            return c.json({"error": "file required"}, 400)
        digest = hashlib.sha256()
        async for chunk in file.stream(64 * 1024):
            digest.update(chunk)
        return c.json(
            {
                "size": file.size,
                "sha256": digest.hexdigest(),
                "temp_disk_bytes": file.size if file.spooled else 0,
            }
        )
