# Competitive capabilities

Evidence reviewed: **2026-07-28**.

This comparison deliberately has **no universal winner and no weighted score**. Django, FastAPI, Hono, and Hayate optimize for different product shapes. Each conclusion below names its capability set; support level and evidence remain visible instead of being collapsed into a marketing percentage.

Support levels: **Core** is in the framework package; **First-party** is maintained by the framework organization; **Platform adapter** is an official deployment-platform path; **External** is a separate community project; **No first-party path** is not a claim that no community solution exists; **Different scope** means the capability is not meaningful for that runtime or product category.

## Profile verdicts

### Portable Python agent API

**Hayate advantaged** — Hayate has the clearest first-party path when one Python application must run on ASGI, native Cloudflare Workers, and buffered or response-streaming AWS Lambda HTTP payload v2 while combining typed HTTP contracts, cached dependency graphs, MCP 2025-11-25, authorization, and checked SQLite/D1 access.

- Against FastAPI: Hayate advantage 7, Parity 6.
- Against Django: Hayate advantage 10, Parity 3.
- Against Hono: Hayate advantage 4, Parity 8, Different scope 1.

### Conventional typed Python API

**Competitive / mixed** — Hayate now meets FastAPI's central typed request/response, OpenAPI, dependency-graph, direct-test, realtime, lifecycle, and sub-application composition capabilities. FastAPI retains a much larger adoption ecosystem; that is a material adoption advantage, not a missing Hayate endpoint feature.

- Against FastAPI: Hayate advantage 1, Parity 9.
- Against Django: Hayate advantage 5, Parity 5.
- Against Hono: Hayate advantage 2, Parity 7, Different scope 1.

### Traditional database-backed full stack

**Competitor advantaged** — Django remains functionally ahead for its model-driven ORM/migrations, integrated forms/templates, bundled localization breadth, and mature extension ecosystem. Hayate now has a first-party explicit operational admin with bounded CRUD, bulk actions, redacted history, searchable relationships, inline editing, saved views, keyset continuations, bounded CSV export, application-scoped localization, constrained branding, and a real-browser accessibility audit on SQLite and native Workers/D1, while retaining a Django admin/ORM application under an ASGI prefix during incremental migration.

- Against FastAPI: Hayate advantage 5, Parity 4.
- Against Django: Hayate advantage 2, Parity 5, Competitor advantage 2.
- Against Hono: Hayate advantage 5, Parity 4.

### JavaScript and TypeScript edge application

**Competitor advantaged** — Hono remains functionally ahead for multi-JavaScript-runtime reach and route-inferred TypeScript RPC, and its JavaScript Workers runtime has materially better startup, memory, CPU, and upload size than Python Workers.

- Against FastAPI: Hayate advantage 2, Parity 4, Different scope 1.
- Against Django: Hayate advantage 4, Parity 2, Different scope 1.
- Against Hono: Hayate advantage 1, Parity 4, Competitor advantage 2.

## Capability matrix

| Capability | Hayate | FastAPI | Django | Hono |
|---|---|---|---|---|
| **Web-standard Fetch core**<br>Application handlers use standard Request/Response/URL/Headers concepts rather than a Python-only server protocol. | **Core** — Fetch-shaped request/response core with ASGI and Workers as adapters. | **No first-party path** — The documented application model is Starlette on ASGI, not a Fetch core. | **No first-party path** — Django documents its own HttpRequest/HttpResponse stack over WSGI or ASGI. | **Core** — Hono explicitly uses Web Standards and the Fetch API. |
| **ASGI server compatibility**<br>The application can run behind ordinary Python ASGI servers. | **Core** — Hayate is directly ASGI-callable and validates HTTP, WebSocket, lifespan, and background work. | **Core** — FastAPI is an ASGI framework built on Starlette. | **Core** — Django documents an async request stack under ASGI. | **Different scope** — Hono targets JavaScript runtimes and their adapters rather than Python ASGI. |
| **Independent sub-application composition**<br>An application can dispatch an independent framework application under a path prefix with correct sub-application path semantics. | **Core** — ASGIPathDispatcher mounts Django, FastAPI, or another ASGI application by longest prefix while keeping the Fetch core and Workers adapter unchanged. | **Core** — FastAPI mounts independent sub-applications with their own routes, OpenAPI, and automatic documentation. | **No first-party path** — Django can be embedded in an outer ASGI composition, but its documented core does not provide a path dispatcher for independent applications. | **Core** — Hono route() composes Hono applications and mount() integrates applications from other Fetch frameworks. |
| **Native Cloudflare Workers path without ASGI**<br>The framework connects Fetch requests directly to its application model without an ASGI protocol bridge. | **Core** — Class and global Python Workers entrypoints convert one Fetch boundary and retain bindings. | **Platform adapter** — Cloudflare supports FastAPI through its Python Workers ASGI server and asgi.fetch bridge. | **No first-party path** — Django documents WSGI/ASGI deployment; no native Fetch adapter is in its framework surface. | **Core** — Cloudflare Workers is a primary Hono runtime and uses app.fetch. |
| **Native AWS Lambda HTTP and response-streaming path**<br>The framework package translates API Gateway HTTP API v2 and Function URL events directly and can incrementally stream responses, without a separately governed ASGI-to-Lambda adapter. | **Core** — to_lambda maps buffered payload-v2 requests directly to the Fetch core, while run_lambda_streaming implements the custom Runtime API's chunking, HTTP metadata, cookies, and error trailers; CI installs the wheel in AWS's Python image and proves first-chunk delivery on the Runtime API wire. | **No first-party path** — FastAPI's deployment documentation delegates other cloud providers to provider guides; the framework package does not include an AWS Lambda event adapter. | **No first-party path** — Django documents WSGI and ASGI deployment and ASGI servers, not a first-party API Gateway or Function URL event adapter. | **Core** — hono/aws-lambda supplies maintained buffered and response-streaming Lambda handlers. |
| **Typed request and response OpenAPI contracts**<br>Types drive input validation, response validation/serialization, OpenAPI 3.1, interactive docs, and client generation. | **First-party** — hayate-openapi 0.7 provides explicit source markers, portable typed constraints, typed binary files, response contracts, pluggable schema providers, OpenAPI 3.1.1, and Scalar on CPython and Python Workers. | **Core** — Type-driven validation, OpenAPI, JSON Schema, and interactive docs are central FastAPI features. | **External** — API schemas and typed REST contracts are provided by projects such as Django REST Framework rather than Django core. | **First-party** — @hono/zod-openapi combines validation, types, and OpenAPI generation. |
| **Resource-bounded multipart file uploads**<br>Multipart files can be consumed incrementally with explicit resource limits, bounded memory, deterministic cleanup, and a disk-free edge path. | **Core** — FormDataLimits caps total body, file, field, part count, and headers; native ASGI parsing streams to a configurable temporary-file threshold while Workers stays bounded without disk, and typed OpenAPI files reuse the same contract. | **Core** — UploadFile provides a spooled file, metadata, and async reads; multipart parsing depends on the separately installed python-multipart package. | **Core** — Django upload handlers stream incoming data and switch between memory and temporary files, with settings and custom handlers for resource policy. | **Core** — Hono exposes Fetch form parsing and whole-body limit middleware, but framework-level multipart spill, per-file, field, part, and header controls are not part of that documented path. |
| **Nested dependency graph with request cache**<br>Endpoint dependencies may have subdependencies and shared results are cached once per request. | **First-party** — hayate-openapi Depends resolves sync/async subdependencies with per-request caching. | **Core** — FastAPI documents arbitrarily deep subdependencies and one-call-per-request caching. | **No first-party path** — Django's documented core feature set does not include a general endpoint dependency-injection graph. | **External** — Hono documents DI options such as Hono Simple DI in its third-party middleware catalog. |
| **First-party MCP Streamable HTTP**<br>The framework organization maintains an MCP transport that mounts into the web app and works on its edge runtime. | **First-party** — hayate-mcp tests MCP 2025-11-25 on ASGI and native Python Workers with the official conformance runner. | **External** — FastAPI-MCP is a separate community project that mounts through ASGI. | **No first-party path** — MCP is not part of Django's documented first-party module set. | **First-party** — @hono/mcp is maintained in the honojs middleware repository and implements Streamable HTTP. |
| **OAuth authorization server, resource server, and DPoP**<br>One maintained stack supplies authorization-server metadata/endpoints, resource protection, scopes, and proof-of-possession support for agent APIs. | **First-party** — hayate-auth and hayate-mcp share principals, scopes, OAuth metadata, and DPoP verification. | **No first-party path** — FastAPI provides OpenAPI-integrated security primitives and tutorials, not a maintained authorization-server product. | **No first-party path** — Django core provides user/password/session authentication and permissions, not OAuth AS plus DPoP. | **No first-party path** — Hono ships auth middleware and MCP auth routing helpers, but not the complete authorization-server and DPoP stack. |
| **One checked SQL contract on SQLite and D1**<br>The same SQL declarations are cardinality-checked and generate typed Python calls for local SQLite and Cloudflare D1. | **First-party** — hayate-sql plus the golden app compile one migration/query set and execute it on SQLite and real D1. | **No first-party path** — FastAPI is database-agnostic and delegates database contracts to external packages. | **No first-party path** — Django has a first-party ORM for documented SQL backends, but not a shared SQLite/Cloudflare D1 checked-SQL path. | **No first-party path** — Hono exposes D1 through the runtime; checked SQL/code generation is delegated to database libraries. |
| **Direct application request testing**<br>Tests can call the application without starting a socket server. | **Core** — app.request executes the Fetch core directly and accepts runtime env bindings. | **Core** — FastAPI documents TestClient for direct application tests. | **Core** — Django provides synchronous and asynchronous test clients. | **Core** — app.request accepts Request data and optional runtime env values. |
| **Safe request correlation and structured access logs**<br>Maintained middleware validates or generates a bounded request ID, exposes it to application and logging code, and returns it across normal and handled-error responses while access logs exclude query strings, headers, and bodies. | **Core** — request_id validates a conservative log-safe X-Request-ID or generates a random replacement, stores it in Context and an async-safe logging context, and returns it through direct, ASGI, Workers, and Lambda paths. logger can emit compact correlated JSON without query strings, headers, or bodies. | **No first-party path** — FastAPI documents authoring custom HTTP middleware and adding ASGI middleware, but its built-in middleware reference does not provide request correlation or a correlated structured access logger. | **No first-party path** — Django provides configurable Python logging and request records, but its bundled middleware stack does not include request correlation or one correlated structured access-log contract. | **Core** — Hono ships requestId middleware with an incoming header, maximum length, custom generator, and Context variable, plus a text access logger with a customizable print function. |
| **WebSocket, streaming, and SSE**<br>The maintained application surface supports bidirectional sockets and incremental HTTP responses. | **Core** — ASGI and Workers adapters preserve WebSockets, streaming bodies, abort signals, and SSE. | **Core** — FastAPI inherits Starlette WebSockets and streaming responses. | **External** — Django supports streaming HTTP, while WebSocket routing is supplied by Django Channels. | **Core** — Hono ships runtime WebSocket helpers and stream/streamSSE helpers. |
| **Lifecycle and background work**<br>The framework exposes startup/shutdown or runtime lifecycle hooks and a supported path for post-response/background work. | **Core** — ASGI lifespan hooks and c.wait_until map to server draining or Workers ctx.waitUntil. | **Core** — FastAPI documents lifespan events and BackgroundTasks. | **Core** — Django 6.0 includes async lifecycle support and a Tasks contract, with execution delegated to infrastructure. | **Core** — Hono exposes runtime execution context including waitUntil on Workers. |
| **Secure operational administration**<br>The ecosystem supplies a maintained internal CRUD UI with bounded list and mutation operations, authorization, and audit evidence. | **First-party** — hayate-admin provides explicit CRUD, search/filter/sort, bounded bulk actions, redacted object history, searchable relationships, and inline editing with per-object authorization on SQLite and native Workers/D1. | **No first-party path** — An administrative UI is not part of FastAPI's documented core feature set. | **Core** — Django's automatic, customizable model admin includes CRUD, actions, and object history. | **No first-party path** — An operational admin UI is not part of Hono's documented framework and helper surface. |
| **Relationship-aware administrative editing**<br>The admin UI derives or explicitly declares bounded relationship choices and inline editing for related records. | **First-party** — hayate-admin explicitly declares bounded searchable to-one choices and reverse inline create/update/delete with preloaded labels, exact authorization, redacted audit, and checked SQLite/D1 writes. | **No first-party path** — An administrative relationship and inline editing surface is not part of FastAPI's documented core feature set. | **Core** — Django admin supplies autocomplete fields and InlineModelAdmin for foreign-key, many-to-many, and generic relationships. | **No first-party path** — An administrative relationship and inline editing surface is not part of Hono's documented framework surface. |
| **Scalable and export-safe admin lists**<br>The maintained admin surface combines named reusable list views, forward keyset continuations, and separately authorized, field/row/byte-bounded CSV exports. | **First-party** — hayate-admin ships static saved views, query-bound opaque keyset continuations, and explicit CSV callbacks with field allowlists, per-object authorization, formula neutralization, and exact row and UTF-8 byte ceilings on SQLite and native Workers/D1. | **No first-party path** — FastAPI does not document a first-party operational admin surface, saved admin views, keyset admin pagination, or CSV export policy. | **Core** — Django admin includes filters, sorting, search, and offset pagination; reusable named views and CSV downloads are application customizations built with ModelAdmin and custom actions rather than one built-in bounded export contract. | **No first-party path** — Hono does not document a first-party operational admin surface or a combined saved-view, keyset-list, and bounded-export contract. |
| **Localized, brandable, accessibility-audited admin**<br>The maintained admin UI can be localized and branded without ambient global state, exposes keyboard and assistive-technology semantics, and carries reproducible real-browser accessibility evidence. | **First-party** — hayate-admin provides immutable per-site message catalogs with English defaults, escaped wordmarks, contrast-checked color/density tokens under a hashed CSP, semantic and keyboard affordances, reduced-motion handling, and pinned axe-core WCAG A/AA checks across real operational flows. | **No first-party path** — FastAPI does not document a first-party administrative UI, localization/branding contract for one, or an admin accessibility gate. | **Core** — Django supplies internationalization, translated admin UI, AdminSite branding and template overrides, and an admin designed for keyboard and assistive-technology access. | **No first-party path** — Hono does not document a first-party operational admin UI or a corresponding localization, branding, and accessibility-audit contract. |
| **Model-driven ORM and migrations**<br>Framework models drive relationships, queries, schema migration generation, and migration execution. | **No first-party path** — Hayate intentionally provides checked SQL rather than a model-driven ORM. | **No first-party path** — FastAPI is database-agnostic and its SQL tutorial composes an external model library. | **Core** — Django models, QuerySets, relationships, and migration commands are first-party core features. | **External** — Hono delegates ORM and migrations to runtime-compatible database packages. |
| **Maintained HTML, forms, and progressive enhancement path**<br>The ecosystem supplies server rendering, form handling, validation, and an executable full-stack starter. | **First-party** — hayate-htmx plus create-hayate provide Jinja, CSRF, fragments, SSE, and tested browser flows. | **External** — FastAPI documents Jinja templates through Starlette and the external Jinja package; form parsing is supported. | **Core** — Django includes templates, forms, validation, generic editing views, messages, and CSRF integration. | **Core** — Hono includes JSX/html helpers and validators across form and request sources. |
| **Multi-JavaScript-runtime portability**<br>The same application runs across Workers, Deno, Bun, Node.js, Fastly, Lambda, and other Fetch runtimes. | **Different scope** — Hayate targets Python runtimes rather than JavaScript runtimes. | **Different scope** — FastAPI targets Python ASGI runtimes. | **Different scope** — Django targets Python WSGI and ASGI runtimes. | **Core** — Hono documents one Web-standards application across a broad JavaScript runtime set. |
| **Maintained typed client path**<br>Server contracts produce a supported TypeScript client or types without manually duplicating request/response shapes. | **First-party** — create-hayate pins OpenAPI TypeScript generation and checks generated artifacts. | **Core** — OpenAPI is built in and the documentation describes automatic client generation. | **External** — Typed API client generation depends on an external schema stack. | **Core** — Hono RPC infers input and output types directly from the chained route type. |
| **Maintained production scaffold**<br>The framework project maintains a generator or template with runnable tests and production-oriented configuration. | **First-party** — create-hayate composes API, Workers, MCP, auth, SQL, OpenAPI, and htmx profiles and validates generated applications. | **First-party** — The FastAPI organization maintains a full-stack production template. | **Core** — django-admin startproject/startapp generate the standard project and application structure. | **First-party** — create-hono generates runtime-specific starters. |

## Evidence

### Web-standard Fetch core

- **Hayate — Core:** Fetch-shaped request/response core with ASGI and Workers as adapters. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/src/hayate/app.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/tests/test_request.py), [evidence 3](https://github.com/hayatepy/hayate/blob/main/tests/test_response.py))
- **FastAPI — No first-party path:** The documented application model is Starlette on ASGI, not a Fetch core. ([source 1](https://fastapi.tiangolo.com/features/))
- **Django — No first-party path:** Django documents its own HttpRequest/HttpResponse stack over WSGI or ASGI. ([source 1](https://docs.djangoproject.com/en/6.0/ref/request-response/))
- **Hono — Core:** Hono explicitly uses Web Standards and the Fetch API. ([source 1](https://hono.dev/docs/concepts/web-standard))
- **Relative to Hayate:** FastAPI: Hayate advantage; Django: Hayate advantage; Hono: Parity.

### ASGI server compatibility

- **Hayate — Core:** Hayate is directly ASGI-callable and validates HTTP, WebSocket, lifespan, and background work. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/src/hayate/adapters/asgi.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/tests/test_asgi.py))
- **FastAPI — Core:** FastAPI is an ASGI framework built on Starlette. ([source 1](https://fastapi.tiangolo.com/features/))
- **Django — Core:** Django documents an async request stack under ASGI. ([source 1](https://docs.djangoproject.com/en/6.0/topics/async/))
- **Hono — Different scope:** Hono targets JavaScript runtimes and their adapters rather than Python ASGI. ([source 1](https://hono.dev/docs/concepts/web-standard))
- **Relative to Hayate:** FastAPI: Parity; Django: Parity; Hono: Different scope.

### Independent sub-application composition

- **Hayate — Core:** ASGIPathDispatcher mounts Django, FastAPI, or another ASGI application by longest prefix while keeping the Fetch core and Workers adapter unchanged. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/src/hayate/adapters/asgi.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/tests/test_asgi_composition.py), [evidence 3](https://github.com/hayatepy/hayate/blob/main/tests/interop/frameworks.py))
- **FastAPI — Core:** FastAPI mounts independent sub-applications with their own routes, OpenAPI, and automatic documentation. ([source 1](https://fastapi.tiangolo.com/advanced/sub-applications/))
- **Django — No first-party path:** Django can be embedded in an outer ASGI composition, but its documented core does not provide a path dispatcher for independent applications. ([source 1](https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/#applying-asgi-middleware))
- **Hono — Core:** Hono route() composes Hono applications and mount() integrates applications from other Fetch frameworks. ([source 1](https://hono.dev/docs/api/hono#mount), [source 2](https://hono.dev/docs/api/routing#grouping))
- **Relative to Hayate:** FastAPI: Parity; Django: Hayate advantage; Hono: Parity.

### Native Cloudflare Workers path without ASGI

- **Hayate — Core:** Class and global Python Workers entrypoints convert one Fetch boundary and retain bindings. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/src/hayate/adapters/workers.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/workers/runner.py))
- **FastAPI — Platform adapter:** Cloudflare supports FastAPI through its Python Workers ASGI server and asgi.fetch bridge. ([source 1](https://developers.cloudflare.com/workers/languages/python/packages/fastapi/))
- **Django — No first-party path:** Django documents WSGI/ASGI deployment; no native Fetch adapter is in its framework surface. ([source 1](https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/))
- **Hono — Core:** Cloudflare Workers is a primary Hono runtime and uses app.fetch. ([source 1](https://hono.dev/docs/getting-started/cloudflare-workers))
- **Relative to Hayate:** FastAPI: Hayate advantage; Django: Hayate advantage; Hono: Parity.

### Native AWS Lambda HTTP and response-streaming path

- **Hayate — Core:** to_lambda maps buffered payload-v2 requests directly to the Fetch core, while run_lambda_streaming implements the custom Runtime API's chunking, HTTP metadata, cookies, and error trailers; CI installs the wheel in AWS's Python image and proves first-chunk delivery on the Runtime API wire. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/src/hayate/adapters/aws.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/tests/test_lambda_adapter.py), [evidence 3](https://github.com/hayatepy/hayate/blob/main/tests/test_lambda_streaming.py), [evidence 4](https://github.com/hayatepy/hayate/blob/main/scripts/check_lambda_runtime.sh), [evidence 5](https://github.com/hayatepy/hayate/blob/main/scripts/check_lambda_streaming_runtime.sh), [evidence 6](https://github.com/hayatepy/hayate/blob/main/examples/lambda-streaming/Dockerfile))
- **FastAPI — No first-party path:** FastAPI's deployment documentation delegates other cloud providers to provider guides; the framework package does not include an AWS Lambda event adapter. ([source 1](https://fastapi.tiangolo.com/deployment/cloud/))
- **Django — No first-party path:** Django documents WSGI and ASGI deployment and ASGI servers, not a first-party API Gateway or Function URL event adapter. ([source 1](https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/))
- **Hono — Core:** hono/aws-lambda supplies maintained buffered and response-streaming Lambda handlers. ([source 1](https://hono.dev/docs/getting-started/aws-lambda))
- **Relative to Hayate:** FastAPI: Hayate advantage; Django: Hayate advantage; Hono: Parity.

### Typed request and response OpenAPI contracts

- **Hayate — First-party:** hayate-openapi 0.7 provides explicit source markers, portable typed constraints, typed binary files, response contracts, pluggable schema providers, OpenAPI 3.1.1, and Scalar on CPython and Python Workers. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/benchmarks/ecosystem/runner.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/docs/ecosystem-compatibility.md), [source 3](https://github.com/hayatepy/hayate-openapi/blob/v0.7.0/README.md))
- **FastAPI — Core:** Type-driven validation, OpenAPI, JSON Schema, and interactive docs are central FastAPI features. ([source 1](https://fastapi.tiangolo.com/features/))
- **Django — External:** API schemas and typed REST contracts are provided by projects such as Django REST Framework rather than Django core. ([source 1](https://www.django-rest-framework.org/topics/documenting-your-api/))
- **Hono — First-party:** @hono/zod-openapi combines validation, types, and OpenAPI generation. ([source 1](https://hono.dev/examples/zod-openapi))
- **Relative to Hayate:** FastAPI: Parity; Django: Hayate advantage; Hono: Parity.

### Resource-bounded multipart file uploads

- **Hayate — Core:** FormDataLimits caps total body, file, field, part count, and headers; native ASGI parsing streams to a configurable temporary-file threshold while Workers stays bounded without disk, and typed OpenAPI files reuse the same contract. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/src/hayate/formdata.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/tests/test_asgi.py), [evidence 3](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/uploads/runner.py), [evidence 4](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/results/2026-07-27-uploads-macos-arm64.md), [source 5](https://github.com/hayatepy/hayate-openapi/blob/v0.7.0/README.md))
- **FastAPI — Core:** UploadFile provides a spooled file, metadata, and async reads; multipart parsing depends on the separately installed python-multipart package. ([source 1](https://fastapi.tiangolo.com/tutorial/request-files/))
- **Django — Core:** Django upload handlers stream incoming data and switch between memory and temporary files, with settings and custom handlers for resource policy. ([source 1](https://docs.djangoproject.com/en/6.0/topics/http/file-uploads/))
- **Hono — Core:** Hono exposes Fetch form parsing and whole-body limit middleware, but framework-level multipart spill, per-file, field, part, and header controls are not part of that documented path. ([source 1](https://hono.dev/docs/api/request), [source 2](https://hono.dev/docs/middleware/builtin/body-limit))
- **Relative to Hayate:** FastAPI: Parity; Django: Parity; Hono: Hayate advantage.

### Nested dependency graph with request cache

- **Hayate — First-party:** hayate-openapi Depends resolves sync/async subdependencies with per-request caching. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/benchmarks/ecosystem/runner.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/docs/ecosystem-compatibility.md))
- **FastAPI — Core:** FastAPI documents arbitrarily deep subdependencies and one-call-per-request caching. ([source 1](https://fastapi.tiangolo.com/tutorial/dependencies/sub-dependencies/))
- **Django — No first-party path:** Django's documented core feature set does not include a general endpoint dependency-injection graph. ([source 1](https://docs.djangoproject.com/en/6.0/contents/))
- **Hono — External:** Hono documents DI options such as Hono Simple DI in its third-party middleware catalog. ([source 1](https://hono.dev/docs/middleware/third-party))
- **Relative to Hayate:** FastAPI: Parity; Django: Hayate advantage; Hono: Hayate advantage.

### First-party MCP Streamable HTTP

- **Hayate — First-party:** hayate-mcp tests MCP 2025-11-25 on ASGI and native Python Workers with the official conformance runner. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/benchmarks/ecosystem/runner.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/docs/ecosystem-compatibility.md))
- **FastAPI — External:** FastAPI-MCP is a separate community project that mounts through ASGI. ([source 1](https://github.com/tadata-org/fastapi_mcp))
- **Django — No first-party path:** MCP is not part of Django's documented first-party module set. ([source 1](https://docs.djangoproject.com/en/6.0/py-modindex))
- **Hono — First-party:** @hono/mcp is maintained in the honojs middleware repository and implements Streamable HTTP. ([source 1](https://www.npmjs.com/package/@hono/mcp))
- **Relative to Hayate:** FastAPI: Hayate advantage; Django: Hayate advantage; Hono: Parity.

### OAuth authorization server, resource server, and DPoP

- **Hayate — First-party:** hayate-auth and hayate-mcp share principals, scopes, OAuth metadata, and DPoP verification. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/benchmarks/ecosystem/runner.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/docs/ecosystem-compatibility.md))
- **FastAPI — No first-party path:** FastAPI provides OpenAPI-integrated security primitives and tutorials, not a maintained authorization-server product. ([source 1](https://fastapi.tiangolo.com/tutorial/security/))
- **Django — No first-party path:** Django core provides user/password/session authentication and permissions, not OAuth AS plus DPoP. ([source 1](https://docs.djangoproject.com/en/6.0/topics/auth/default/))
- **Hono — No first-party path:** Hono ships auth middleware and MCP auth routing helpers, but not the complete authorization-server and DPoP stack. ([source 1](https://hono.dev/docs/guides/middleware), [source 2](https://www.npmjs.com/package/@hono/mcp))
- **Relative to Hayate:** FastAPI: Hayate advantage; Django: Hayate advantage; Hono: Hayate advantage.

### One checked SQL contract on SQLite and D1

- **Hayate — First-party:** hayate-sql plus the golden app compile one migration/query set and execute it on SQLite and real D1. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/benchmarks/ecosystem/runner.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/docs/ecosystem-compatibility.md))
- **FastAPI — No first-party path:** FastAPI is database-agnostic and delegates database contracts to external packages. ([source 1](https://fastapi.tiangolo.com/tutorial/sql-databases/))
- **Django — No first-party path:** Django has a first-party ORM for documented SQL backends, but not a shared SQLite/Cloudflare D1 checked-SQL path. ([source 1](https://docs.djangoproject.com/en/6.0/ref/databases/))
- **Hono — No first-party path:** Hono exposes D1 through the runtime; checked SQL/code generation is delegated to database libraries. ([source 1](https://hono.dev/examples/cloudflare-d1))
- **Relative to Hayate:** FastAPI: Hayate advantage; Django: Hayate advantage; Hono: Hayate advantage.

### Direct application request testing

- **Hayate — Core:** app.request executes the Fetch core directly and accepts runtime env bindings. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/src/hayate/app.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/tests/test_app.py))
- **FastAPI — Core:** FastAPI documents TestClient for direct application tests. ([source 1](https://fastapi.tiangolo.com/tutorial/testing/))
- **Django — Core:** Django provides synchronous and asynchronous test clients. ([source 1](https://docs.djangoproject.com/en/6.0/topics/testing/tools/))
- **Hono — Core:** app.request accepts Request data and optional runtime env values. ([source 1](https://hono.dev/docs/guides/testing))
- **Relative to Hayate:** FastAPI: Parity; Django: Parity; Hono: Parity.

### Safe request correlation and structured access logs

- **Hayate — Core:** request_id validates a conservative log-safe X-Request-ID or generates a random replacement, stores it in Context and an async-safe logging context, and returns it through direct, ASGI, Workers, and Lambda paths. logger can emit compact correlated JSON without query strings, headers, or bodies. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/src/hayate/middleware/request_id.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/src/hayate/middleware/logger.py), [evidence 3](https://github.com/hayatepy/hayate/blob/main/tests/test_middleware.py), [evidence 4](https://github.com/hayatepy/hayate/blob/main/tests/test_asgi.py), [evidence 5](https://github.com/hayatepy/hayate/blob/main/tests/test_workers_adapter.py), [evidence 6](https://github.com/hayatepy/hayate/blob/main/tests/test_lambda_adapter.py))
- **FastAPI — No first-party path:** FastAPI documents authoring custom HTTP middleware and adding ASGI middleware, but its built-in middleware reference does not provide request correlation or a correlated structured access logger. ([source 1](https://fastapi.tiangolo.com/tutorial/middleware/), [source 2](https://fastapi.tiangolo.com/reference/middleware/))
- **Django — No first-party path:** Django provides configurable Python logging and request records, but its bundled middleware stack does not include request correlation or one correlated structured access-log contract. ([source 1](https://docs.djangoproject.com/en/6.0/topics/http/middleware/), [source 2](https://docs.djangoproject.com/en/6.0/ref/middleware/), [source 3](https://docs.djangoproject.com/en/6.0/ref/logging/))
- **Hono — Core:** Hono ships requestId middleware with an incoming header, maximum length, custom generator, and Context variable, plus a text access logger with a customizable print function. ([source 1](https://hono.dev/docs/middleware/builtin/request-id), [source 2](https://hono.dev/docs/middleware/builtin/logger))
- **Relative to Hayate:** FastAPI: Hayate advantage; Django: Hayate advantage; Hono: Parity.

### WebSocket, streaming, and SSE

- **Hayate — Core:** ASGI and Workers adapters preserve WebSockets, streaming bodies, abort signals, and SSE. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/src/hayate/websocket.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/tests/test_sse.py), [evidence 3](https://github.com/hayatepy/hayate/blob/main/tests/test_workers_adapter.py))
- **FastAPI — Core:** FastAPI inherits Starlette WebSockets and streaming responses. ([source 1](https://fastapi.tiangolo.com/advanced/websockets/), [source 2](https://fastapi.tiangolo.com/features/))
- **Django — External:** Django supports streaming HTTP, while WebSocket routing is supplied by Django Channels. ([source 1](https://docs.djangoproject.com/en/6.0/ref/request-response/#streaminghttpresponse-objects), [source 2](https://channels.readthedocs.io/en/stable/))
- **Hono — Core:** Hono ships runtime WebSocket helpers and stream/streamSSE helpers. ([source 1](https://hono.dev/docs/helpers/websocket), [source 2](https://hono.dev/docs/helpers/streaming))
- **Relative to Hayate:** FastAPI: Parity; Django: Hayate advantage; Hono: Parity.

### Lifecycle and background work

- **Hayate — Core:** ASGI lifespan hooks and c.wait_until map to server draining or Workers ctx.waitUntil. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/tests/test_asgi.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/docs/guide/runtimes.md))
- **FastAPI — Core:** FastAPI documents lifespan events and BackgroundTasks. ([source 1](https://fastapi.tiangolo.com/advanced/events/), [source 2](https://fastapi.tiangolo.com/tutorial/background-tasks/))
- **Django — Core:** Django 6.0 includes async lifecycle support and a Tasks contract, with execution delegated to infrastructure. ([source 1](https://docs.djangoproject.com/en/6.0/topics/async/), [source 2](https://docs.djangoproject.com/en/6.0/ref/tasks/))
- **Hono — Core:** Hono exposes runtime execution context including waitUntil on Workers. ([source 1](https://hono.dev/docs/api/context#executionctx))
- **Relative to Hayate:** FastAPI: Parity; Django: Parity; Hono: Parity.

### Secure operational administration

- **Hayate — First-party:** hayate-admin provides explicit CRUD, search/filter/sort, bounded bulk actions, redacted object history, searchable relationships, and inline editing with per-object authorization on SQLite and native Workers/D1. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/docs/ecosystem-compatibility.md))
- **FastAPI — No first-party path:** An administrative UI is not part of FastAPI's documented core feature set. ([source 1](https://fastapi.tiangolo.com/features/))
- **Django — Core:** Django's automatic, customizable model admin includes CRUD, actions, and object history. ([source 1](https://docs.djangoproject.com/en/6.0/ref/contrib/admin/), [source 2](https://docs.djangoproject.com/en/6.0/ref/contrib/admin/actions/))
- **Hono — No first-party path:** An operational admin UI is not part of Hono's documented framework and helper surface. ([source 1](https://hono.dev/docs/))
- **Relative to Hayate:** FastAPI: Hayate advantage; Django: Parity; Hono: Hayate advantage.

### Relationship-aware administrative editing

- **Hayate — First-party:** hayate-admin explicitly declares bounded searchable to-one choices and reverse inline create/update/delete with preloaded labels, exact authorization, redacted audit, and checked SQLite/D1 writes. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/docs/ecosystem-compatibility.md))
- **FastAPI — No first-party path:** An administrative relationship and inline editing surface is not part of FastAPI's documented core feature set. ([source 1](https://fastapi.tiangolo.com/features/))
- **Django — Core:** Django admin supplies autocomplete fields and InlineModelAdmin for foreign-key, many-to-many, and generic relationships. ([source 1](https://docs.djangoproject.com/en/6.0/ref/contrib/admin/))
- **Hono — No first-party path:** An administrative relationship and inline editing surface is not part of Hono's documented framework surface. ([source 1](https://hono.dev/docs/))
- **Relative to Hayate:** FastAPI: Hayate advantage; Django: Parity; Hono: Hayate advantage.

### Scalable and export-safe admin lists

- **Hayate — First-party:** hayate-admin ships static saved views, query-bound opaque keyset continuations, and explicit CSV callbacks with field allowlists, per-object authorization, formula neutralization, and exact row and UTF-8 byte ceilings on SQLite and native Workers/D1. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/docs/ecosystem-compatibility.md))
- **FastAPI — No first-party path:** FastAPI does not document a first-party operational admin surface, saved admin views, keyset admin pagination, or CSV export policy. ([source 1](https://fastapi.tiangolo.com/features/))
- **Django — Core:** Django admin includes filters, sorting, search, and offset pagination; reusable named views and CSV downloads are application customizations built with ModelAdmin and custom actions rather than one built-in bounded export contract. ([source 1](https://docs.djangoproject.com/en/6.0/intro/tutorial07/), [source 2](https://docs.djangoproject.com/en/6.0/ref/contrib/admin/actions/))
- **Hono — No first-party path:** Hono does not document a first-party operational admin surface or a combined saved-view, keyset-list, and bounded-export contract. ([source 1](https://hono.dev/docs/))
- **Relative to Hayate:** FastAPI: Hayate advantage; Django: Hayate advantage; Hono: Hayate advantage.

### Localized, brandable, accessibility-audited admin

- **Hayate — First-party:** hayate-admin provides immutable per-site message catalogs with English defaults, escaped wordmarks, contrast-checked color/density tokens under a hashed CSP, semantic and keyboard affordances, reduced-motion handling, and pinned axe-core WCAG A/AA checks across real operational flows. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/docs/ecosystem-compatibility.md))
- **FastAPI — No first-party path:** FastAPI does not document a first-party administrative UI, localization/branding contract for one, or an admin accessibility gate. ([source 1](https://fastapi.tiangolo.com/features/))
- **Django — Core:** Django supplies internationalization, translated admin UI, AdminSite branding and template overrides, and an admin designed for keyboard and assistive-technology access. ([source 1](https://docs.djangoproject.com/en/6.0/topics/i18n/translation/), [source 2](https://docs.djangoproject.com/en/6.0/ref/contrib/admin/), [source 3](https://docs.djangoproject.com/en/6.0/faq/admin/#is-django-s-admin-interface-accessible))
- **Hono — No first-party path:** Hono does not document a first-party operational admin UI or a corresponding localization, branding, and accessibility-audit contract. ([source 1](https://hono.dev/docs/))
- **Relative to Hayate:** FastAPI: Hayate advantage; Django: Parity; Hono: Hayate advantage.

### Model-driven ORM and migrations

- **Hayate — No first-party path:** Hayate intentionally provides checked SQL rather than a model-driven ORM. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/DESIGN.md))
- **FastAPI — No first-party path:** FastAPI is database-agnostic and its SQL tutorial composes an external model library. ([source 1](https://fastapi.tiangolo.com/tutorial/sql-databases/))
- **Django — Core:** Django models, QuerySets, relationships, and migration commands are first-party core features. ([source 1](https://docs.djangoproject.com/en/6.0/topics/db/models/), [source 2](https://docs.djangoproject.com/en/6.0/ref/django-admin/#makemigrations))
- **Hono — External:** Hono delegates ORM and migrations to runtime-compatible database packages. ([source 1](https://hono.dev/docs/middleware/third-party))
- **Relative to Hayate:** FastAPI: Parity; Django: Competitor advantage; Hono: Parity.

### Maintained HTML, forms, and progressive enhancement path

- **Hayate — First-party:** hayate-htmx plus create-hayate provide Jinja, CSRF, fragments, SSE, and tested browser flows. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/benchmarks/ecosystem/runner.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/docs/ecosystem-compatibility.md))
- **FastAPI — External:** FastAPI documents Jinja templates through Starlette and the external Jinja package; form parsing is supported. ([source 1](https://fastapi.tiangolo.com/advanced/templates/), [source 2](https://fastapi.tiangolo.com/tutorial/request-forms/))
- **Django — Core:** Django includes templates, forms, validation, generic editing views, messages, and CSRF integration. ([source 1](https://docs.djangoproject.com/en/6.0/topics/forms/), [source 2](https://docs.djangoproject.com/en/6.0/topics/templates/))
- **Hono — Core:** Hono includes JSX/html helpers and validators across form and request sources. ([source 1](https://hono.dev/docs/guides/jsx), [source 2](https://hono.dev/docs/guides/validation))
- **Relative to Hayate:** FastAPI: Hayate advantage; Django: Competitor advantage; Hono: Parity.

### Multi-JavaScript-runtime portability

- **Hayate — Different scope:** Hayate targets Python runtimes rather than JavaScript runtimes. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/docs/guide/runtimes.md))
- **FastAPI — Different scope:** FastAPI targets Python ASGI runtimes. ([source 1](https://fastapi.tiangolo.com/features/))
- **Django — Different scope:** Django targets Python WSGI and ASGI runtimes. ([source 1](https://docs.djangoproject.com/en/6.0/howto/deployment/))
- **Hono — Core:** Hono documents one Web-standards application across a broad JavaScript runtime set. ([source 1](https://hono.dev/docs/concepts/web-standard))
- **Relative to Hayate:** FastAPI: Different scope; Django: Different scope; Hono: Competitor advantage.

### Maintained typed client path

- **Hayate — First-party:** create-hayate pins OpenAPI TypeScript generation and checks generated artifacts. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/benchmarks/ecosystem/runner.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/docs/ecosystem-compatibility.md))
- **FastAPI — Core:** OpenAPI is built in and the documentation describes automatic client generation. ([source 1](https://fastapi.tiangolo.com/features/))
- **Django — External:** Typed API client generation depends on an external schema stack. ([source 1](https://www.django-rest-framework.org/topics/documenting-your-api/))
- **Hono — Core:** Hono RPC infers input and output types directly from the chained route type. ([source 1](https://hono.dev/docs/guides/rpc))
- **Relative to Hayate:** FastAPI: Parity; Django: Hayate advantage; Hono: Competitor advantage.

### Maintained production scaffold

- **Hayate — First-party:** create-hayate composes API, Workers, MCP, auth, SQL, OpenAPI, and htmx profiles and validates generated applications. ([evidence 1](https://github.com/hayatepy/hayate/blob/main/benchmarks/ecosystem/runner.py), [evidence 2](https://github.com/hayatepy/hayate/blob/main/docs/ecosystem-compatibility.md))
- **FastAPI — First-party:** The FastAPI organization maintains a full-stack production template. ([source 1](https://github.com/fastapi/full-stack-fastapi-template))
- **Django — Core:** django-admin startproject/startapp generate the standard project and application structure. ([source 1](https://docs.djangoproject.com/en/6.0/ref/django-admin/#startproject))
- **Hono — First-party:** create-hono generates runtime-specific starters. ([source 1](https://hono.dev/docs/getting-started/basic))
- **Relative to Hayate:** FastAPI: Parity; Django: Parity; Hono: Parity.

## Interpretation guardrails

- The performance benchmark and its 14-point HTTP contract remain a same-workload result, not a universal standards or feature score.
- A missing first-party path does not mean that no third-party package exists. It means adoption requires an independently governed component.
- Ecosystem size, maintainer capacity, long-term stability, and production track record are adoption factors but are not mislabeled as framework APIs.
- Update the dated source data and regenerate this file when a compared framework adds or removes a relevant capability.

Regenerate with:

```sh
uv run python benchmarks/competitive/capabilities.py
```
