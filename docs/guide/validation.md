# Validation

The core ships a hook, not a schema library: `validator(target, validate)`
takes **any callable** that turns raw data into a validated value (or
raises). Failures become RFC 9457 problems (400).

```python
from hayate import Hayate, validator

def require_title(data: dict) -> dict:
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("'title' must be a non-empty string")
    return {"title": title.strip()}

app = Hayate()

@app.post("/books", validator("json", require_title))
async def create(c):
    book = c.req.valid("json")   # the validated value
    ...
```

Targets: `"json"` (parsed body), `"form"` (urlencoded/multipart fields),
`"query"` (search params).

## msgspec

Because the hook is just a callable, schema libraries plug in directly — no
adapter packages:

```python
import msgspec

class BookIn(msgspec.Struct):
    title: str
    year: int

@app.post("/books", validator("json", lambda data: msgspec.convert(data, BookIn)))
async def create(c):
    book: BookIn = c.req.valid("json")
    return c.json({"title": book.title}, 201)
```

## pydantic

```python
from pydantic import BaseModel, TypeAdapter

class BookIn(BaseModel):
    title: str
    year: int

@app.post("/books", validator("json", TypeAdapter(BookIn).validate_python))
async def create(c):
    book: BookIn = c.req.valid("json")
    ...
```

A malformed JSON body short-circuits with a distinct message
(`"request body is not valid JSON"`) before your validator runs.
