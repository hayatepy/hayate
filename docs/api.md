# API reference

The public surface, generated from the source. Semantics follow the Fetch /
URL / URLPattern standards; spelling follows PEP 8 (`searchParams` →
`search_params`, `getSetCookie()` → `set_cookie_list()`).

## Application

::: hayate.Hayate

::: hayate.Route

## ASGI composition

::: hayate.adapters.asgi.ASGIPathDispatcher

## Context

::: hayate.Context

## Requests

::: hayate.Request

::: hayate.HayateRequest

## Forms and files

::: hayate.FormData

::: hayate.File

::: hayate.FormDataLimits

::: hayate.FormDataError

::: hayate.FormDataLimitError

## Responses

::: hayate.Response

::: hayate.HTTPException

::: hayate.problem

## Cookies

::: hayate.parse_cookies

::: hayate.serialize_set_cookie

## Primitives

::: hayate.Headers

::: hayate.URL

::: hayate.URLSearchParams

::: hayate.URLPattern

::: hayate.AbortSignal

## Realtime

::: hayate.WebSocket

::: hayate.WebSocketClosed

## Validation

::: hayate.validator

## Deferred work

::: hayate.ExecutionContext
