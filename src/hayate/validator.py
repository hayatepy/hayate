"""Request validation hook (DESIGN.md §9.2).

The core stays dependency-free: ``validator(target, validate)`` accepts
any callable that turns raw data into a validated value (or raises).
Schema libraries plug in directly — no adapter package needed:

    import msgspec

    class BookIn(msgspec.Struct):
        title: str

    @app.post("/books", validator("json", lambda data: msgspec.convert(data, BookIn)))
    async def create(c):
        book = c.req.valid("json")   # BookIn instance

    # pydantic works the same way:
    #   validator("json", TypeAdapter(BookIn).validate_python)

Targets: ``json`` (parsed body), ``form`` (urlencoded/multipart fields,
last value wins), ``query`` (search params, last value wins). Failures
become RFC 9457 problem responses (400) with the validator's message as
``detail``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from .context import Context, Middleware, Next
from .exceptions import HTTPException

type ValidationTarget = Literal["json", "form", "query"]

_TARGETS = ("json", "form", "query")


def validator(target: ValidationTarget, validate: Callable[[Any], Any]) -> Middleware:
    if target not in _TARGETS:
        raise ValueError(f"unknown validation target {target!r}; expected one of {_TARGETS}")

    async def validator_middleware(c: Context, next_: Next) -> None:
        data: Any
        if target == "json":
            try:
                data = await c.req.json()
            except Exception:
                raise HTTPException(
                    400, title="Validation failed", detail="request body is not valid JSON"
                ) from None
        elif target == "form":
            data = dict(await c.req.form_data())
        else:
            data = dict(c.req.url.search_params)
        try:
            validated = validate(data)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, title="Validation failed", detail=str(exc)) from exc
        c.req._set_valid(target, validated)
        await next_()

    return validator_middleware
