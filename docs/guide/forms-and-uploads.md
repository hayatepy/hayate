# Forms and uploads

`Request.form_data()` parses URL-encoded and multipart bodies into the same
ordered `FormData` / `File` surface on ASGI, Cloudflare Python Workers, direct
tests, and AWS Lambda.

## Bounded parsing

The zero-argument call uses conservative defaults:

| Limit | Default |
|---|---:|
| Complete form body | 32 MiB |
| One file | 32 MiB |
| One text field | 1 MiB |
| Parts | 1,000 |
| Headers per part | 16 KiB |
| Native in-memory file threshold | 1 MiB |

Set an application-specific contract explicitly:

```python
from hayate import (
    File,
    FormDataError,
    FormDataLimitError,
    FormDataLimits,
    HTTPException,
)
from hayate.middleware import body_limit

upload_limits = FormDataLimits(
    max_body_bytes=12 * 1024 * 1024,
    max_file_bytes=10 * 1024 * 1024,
    max_field_bytes=64 * 1024,
    max_parts=20,
    max_header_bytes=8 * 1024,
    file_memory_bytes=512 * 1024,
)


@app.post("/documents", body_limit(max_size=12 * 1024 * 1024))
async def documents(c):
    try:
        form = await c.req.form_data(upload_limits)
    except FormDataLimitError as exc:
        raise HTTPException(413, title="Payload Too Large", detail=str(exc)) from exc
    except FormDataError as exc:
        raise HTTPException(400, title="Invalid form", detail=str(exc)) from exc

    async with form:
        upload = form.get("file")
        if not isinstance(upload, File):
            raise HTTPException(400, title="A file is required")

        async for chunk in upload.stream():
            await destination.write(chunk)

    return c.json({"stored": True}, 201)
```

`body_limit()` is the coarse transport guard. `FormDataLimits` is a second
parser-level boundary that also limits part counts, individual fields, and
part headers.

## Native spooling and Workers

On native Python, a streamed multipart file stays in memory until
`file_memory_bytes` and then moves to an unnamed temporary file. `File.stream()`
reads that file in bounded chunks; `File.bytes()` and `File.text()` remain
available for compatible existing code.

On Workers/Pyodide, Hayate never claims filesystem spooling. The same parser
stays extension-free and rejects input at the configured limits. Choose a
Workers limit that fits the platform and stream accepted content to R2 or
another application-owned destination as early as the deployment permits.

Use `async with form` or `await form.close()` to release native temporary files
deterministically. Parser failures and exceeded limits close partial files
automatically.

## Validation

The core `validator("form", ...)` converts malformed forms to RFC 9457 `400`
responses and configured limit failures to `413`. It keeps uploaded files open
through the downstream handler and closes them on success or failure when the
middleware unwinds. `hayate-openapi` typed form parameters use the same
`FormData` and `File` values; multipart schemas do not create a second upload
type.
