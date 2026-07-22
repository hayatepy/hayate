# hayate 設計ドキュメント

> Hono を参考に、「最新の Web 標準に即すこと」だけを設計の中心に置いた Python Web フレームワーク。
> 本書は実装前の設計判断を観点別にまとめた内部設計メモ(日本語)。公開ドキュメントは英語先行(§15)。
> 各節は「決定 / 理由 / 却下した代替案」の形を基本とする。

## TL;DR

- **コンセプトは一文で「Fetch API を Python の第一級市民にする」**。ユーザーが触る API はすべて WHATWG / IETF 標準の概念に 1:1 対応させ、WSGI / ASGI という Python ローカル規格は実装詳細(アダプタ層)に格下げする。
- アプリケーションの本体は `fetch(Request) -> Response` の純粋な非同期関数。ASGI サーバー、Cloudflare Python Workers、AWS Lambda はすべて「アダプタ」。
- ルーティング構文は独自 DSL ではなく **WHATWG URLPattern 標準**を採用(Hono の `/:id` 構文は URLPattern のサブセットなのでそのまま動く)。
- コアは**ゼロ依存**(標準ライブラリのみ)、async-first、PEP 695 世代の型付け。
- バリデーション・テンプレート・ORM・DI はコアに入れない。Hono 同様、薄いフックと公式ミドルウェアで対応する。
- **命名**: hayate(疾風)。Hono(炎)と同じ「自然現象の日本語一語」の系譜で、haya-inc の haya(速)を含む。PyPI 空き確認済み(2026-07-22 時点)。

```python
from hayate import Hayate, Context

app = Hayate()

@app.get("/books/:id")
async def show_book(c: Context):
    book = await find_book(c.req.param("id"))
    if book is None:
        raise HTTPException(404, title="Book not found")
    return c.json(book)
```

---

## 1. なぜ作るか

### 1.1 JS 世界で起きたこと(前提認識)

Hono の成功の本質は「速さ」ではなく「**Node 独自 API を捨てて Web 標準(Request / Response / URL / Streams)だけに依存した**」ことにある。その結果:

- Cloudflare Workers / Deno / Bun / Node / Lambda で**同一コードが動く**(ランタイム側が標準を実装しているから)
- 学習コストが MDN のドキュメントに外部化される(フレームワーク独自概念が最小)
- `app.request()` でサーバー起動なしにテストできる(ハンドラが純関数だから)

この動きは Ecma TC55(WinterTC)の「Minimum Common Web API」として標準化され、2025 年に第 1 版が発行された。「サーバーランタイムが実装すべき Web API のサブセット」という共通認識が JS 世界には確立している。

### 1.2 Python 世界のギャップ

| フレームワーク | リクエスト/レスポンスモデル | 問題 |
|---|---|---|
| FastAPI / Starlette | ASGI scope の独自ラッパー | Web 標準と語彙が無関係。`request.url` は独自クラス、Headers 意味論も独自 |
| Django / Flask | WSGI 世代の独自オブジェクト | 同上 + 同期前提の歴史的経緯 |
| Litestar / BlackSheep | 独自モデル | 同上 |
| Cloudflare Python Workers | JS の Request/Response を FFI で露出 | Fetch モデルだが Workers 専用。汎用フレームワークではない |

つまり「**JS 開発者が Hono / Workers / Deno で身につけた概念がそのまま通用する Python フレームワーク**」は存在しない。WSGI(2003)/ ASGI(2018)は Python ローカルの規格であり、HTTP そのものの標準(RFC 9110 系)や Fetch 標準とは独立に進化した方言である。

### 1.3 賭け(なぜ今か)

- サーバーレス / エッジ / AI エージェントの時代、HTTP ハンドラは「Request → Response の純関数」に収束しつつある。Python にもその形の器が要る。
- Cloudflare が Python Workers(Pyodide)で Fetch モデルを Python に持ち込み始めた。標準準拠のフレームワークがあれば同一コードでエッジと自前サーバーの両方を狙える。
- Python 3.12+(PEP 695 generics)、3.13+(free-threading)、3.14(`compression.zstd`)でコアをモダンに保つ条件が揃った。

**勝負しない領域**: 生のスループットで Rust 系(Granian/Robyn)には勝てないし勝負しない。土俵は「標準準拠」「移植性」「テスト容易性」「学習コストの外部化」。ただし pure Python として Starlette 同等の性能は必達ラインとする。

---

## 2. 規範とする標準(Normative References)

「Web 標準に対応物がない機能はコアに入れない」を機能追加の門番ルールとする。

| 標準 | 発行元 | hayate での対応 |
|---|---|---|
| Fetch Standard(Request / Response / Headers / Body) | WHATWG | コアオブジェクトモデル(§4) |
| URL Standard(URL / URLSearchParams) | WHATWG | `hayate.URL` / `hayate.URLSearchParams` |
| **URLPattern Standard** | WHATWG | ルーティング構文の唯一の基盤(§6) |
| Minimum Common Web API(2025 年版) | Ecma TC55 (WinterTC) | 提供 API の選定基準 |
| HTTP Semantics — RFC 9110 | IETF | メソッド / ステータス / ネゴシエーション / 条件付きリクエスト |
| HTTP Caching — RFC 9111 | IETF | `cache` ミドルウェア、Cache-Control ヘルパー |
| HTTP/1.1, /2, /3 — RFC 9112–9114 | IETF | **アダプタ/サーバー層の責務**。コアはワイヤ形式に非依存 |
| Cookies — RFC 6265bis | IETF | cookie ヘルパー(SameSite / `__Host-` 接頭辞 / 署名) |
| Problem Details — RFC 9457 | IETF | エラーレスポンスの既定形式(§11) |
| Structured Field Values — RFC 9651 | IETF | ヘッダーパーサユーティリティ `hayate.http.sfv` |
| multipart/form-data — RFC 7578 | IETF | `await request.form_data()` |
| Server-Sent Events | WHATWG HTML | SSE ヘルパー(§10) |
| WebSocket — RFC 6455 / WebSocket API | IETF / WHATWG | `app.ws()`(v0.2) |
| Early Hints — RFC 8297 | IETF | 将来(ASGI 拡張の普及待ち) |
| Trace Context(traceparent) | W3C | `request_id` ミドルウェア / OTel 連携 |
| Fetch Metadata(Sec-Fetch-*) | W3C | `secure_headers` / CSRF 対策 |

---

## 3. アーキテクチャ

### 3.1 層構造

```
ユーザーコード: handler / middleware     ← Web 標準の語彙だけで書く
─────────────────────────────────────
hayate コア: App / Router / Context
             Request / Response / Headers / URL / URLPattern
─────────────────────────────────────
アダプタ: ASGI | Cloudflare Workers | AWS Lambda | testing
─────────────────────────────────────
実行環境: uvicorn / granian / hypercorn | workerd | Lambda
```

### 3.2 心臓部は `fetch`

コアの唯一のエントリポイントは以下のシグネチャ(Hono の `app.fetch` / Workers の `on_fetch` と同型):

```python
async def fetch(self, request: Request, env: Env | None = None) -> Response: ...
```

- コアは I/O を一切行わない(ソケットもイベントループ起動も知らない)。**「Request を受け取り Response を返す」以外の責務を持たない**。
- この純粋性が、テスト容易性(§13)とマルチランタイム(§12)の両方を無料で手に入れる根拠。
- ASGI ⇔ Fetch の変換はアダプタが行う。ユーザーは `scope` / `receive` / `send` を見ることは一生ない。

**却下した代替案**: Starlette 型「ASGI を薄くラップ」— ASGI の語彙がユーザー API に漏れ、Workers 等の非 ASGI ランタイムでコードが再利用できない。本プロジェクトの存在意義と正面衝突するため却下。

---

## 4. コアオブジェクトモデル

Fetch 標準の**意味論**(不変条件・状態遷移・エラー条件)に準拠した自前実装。ゼロ依存。

### 4.1 Request

```python
class Request:
    method: str                      # 正規化済み大文字
    url: URL                         # WHATWG URL
    headers: Headers
    body: AsyncIterable[bytes] | None
    signal: AbortSignal              # クライアント切断の通知

    async def bytes(self) -> bytes        # Fetch 標準の .bytes()
    async def text(self) -> str
    async def json(self) -> Any
    async def form_data(self) -> FormData # urlencoded / multipart 両対応
    def clone(self) -> Request
    @property
    def body_used(self) -> bool           # 消費は一回(Fetch 準拠)
```

- Body の二重読み取りはエラー(Fetch の `bodyUsed` 意味論)。`clone()` は内部バッファ共有で両方読めるようにする(`tee()` 相当)。
- ルートパラメータ等のサーバー固有情報は Request を汚さず Context 側に置く(Fetch 標準にないものを標準オブジェクトに生やさない)。

### 4.2 Response

```python
Response(body=None, status=200, headers=None)   # Fetch のコンストラクタ形状
Response.redirect(location, status=302)
```

- body に許すのは `None | bytes | str | AsyncIterable[bytes]` の 4 型のみ。ストリーミングは async iterable を渡すだけ(専用 API を増やさない)。
- Fetch の静的 `Response.json()` は**提供しない**(実装で確定): Python ではボディ読み取りの `await res.json()` と同名のクラスメソッドを共存できない。JSON ビルダーは `c.json()` が担う。

### 4.3 Headers

- 大文字小文字非区別・挿入順保持・複数値対応(内部はタプルのリスト)。
- `get()` はカンマ結合(Fetch 準拠)、`Set-Cookie` だけは結合してはならないので `set_cookie_list()`(Fetch の `getSetCookie()` 対応)を用意。
- Fetch の immutable guard 意味論を採用: アダプタから来た `request.headers` は不変。

### 4.4 URL / URLSearchParams / URLPattern

- **URL**: WHATWG URL 意味論の実用部分集合を自前実装。`urllib.parse` は RFC 3986 系で WHATWG パーサと挙動が異なるため、内部利用に留めて表面には出さない。準拠度は wpt(web-platform-tests)の該当テストベクタをベンダリングして CI で計測する(§13)。
- **URLPattern**: ルーティングの基盤(§6)。`pathname` 成分を中心に実装し、`exec()` / `test()` を提供。

### 4.5 AbortSignal

- `request.signal` でクライアント切断を観測可能にする。実装は asyncio の cancellation とブリッジ。
- 既定ではハンドラを強制キャンセルしない(Hono と同じ安全側)。切断時中断は `timeout` / `abort_on_disconnect` ミドルウェアで opt-in。

### 4.6 Streams の扱い(意図的な簡略化)

WHATWG ReadableStream のフル実装は**しない**。Python には `AsyncIterable[bytes]` という慣用表現があり、ストリーム消費・逐次処理というスペックの目的を満たす。`tee` / `cancel` に相当する最小機能は `clone()` と `signal` に内包する。「標準の意味論に従うが、言語慣用と冗長に競合する API 形状までは輸入しない」— この線引きは §5 の命名方針と同じ原則。

---

## 5. 命名規則: 意味論は標準、表記は PEP 8

**決定**: プロパティ / メソッド名は snake_case(`search_params`, `form_data()`)。ただし概念・意味論・状態遷移は Fetch 標準に厳密対応させ、ドキュメントに **camelCase ⇔ snake_case 対応表**を必ず併記する。

| Web 標準 | hayate |
|---|---|
| `url.searchParams` | `url.search_params` |
| `await req.arrayBuffer()` / `await req.bytes()` | `await req.bytes()` |
| `req.bodyUsed` | `req.body_used` |
| `headers.getSetCookie()` | `headers.set_cookie_list()` |
| `URLPattern.exec()` | `pattern.exec()`(予約語でないのでそのまま) |

**理由**: Pyodide のように camelCase を露出すると Python エコシステム(linter, 慣習)と衝突し「Python のフリをした JS」になる。標準準拠の価値は**名前の字面**ではなく**挙動の予測可能性**(MDN を読めば hayate の挙動がわかる)にある。

---

## 6. ルーティング

### 6.1 構文 = URLPattern 標準

独自ルーティング DSL を**発明しない**。WHATWG URLPattern の pathname 構文をそのまま使う:

```python
@app.get("/books/:id")           # 名前付きパラメータ
@app.get("/books/:id(\\d+)")     # 正規表現制約
@app.get("/files/*")             # ワイルドカード
@app.get("/users{/:lang}?")      # オプショナルグループ
```

- Hono の `/:id` 構文は URLPattern のサブセットなので、Hono ユーザーの知識がそのまま使える。
- Node / Deno / Bun / ブラウザに実装済みの標準なので、構文の学習・議論・エッジケース定義をすべて標準に外部化できる。
- v0 では pathname のみ対象(method × pathname でルーティング)。hostname 等の他成分マッチは需要が出るまでやらない(YAGNI)。

### 6.2 ルーターアルゴリズム

- **v0 は単一実装**: 登録時に全ルートをコンパイル → 静的パスは dict 完全一致、動的パスは事前コンパイル済み正規表現の登録順走査(セグメント trie 化はベンチマークが必要性を示したら — 証拠駆動)。
- Hono の SmartRouter(複数ルーター切替)は**採用しない**。KISS 違反(利用者が選択を迫られる)であり、Python では起動時コンパイル一本で十分。プロファイルで問題が出たら初めて検討する(証拠駆動)。
- `405 Method Not Allowed`(+ `Allow` ヘッダー)と `HEAD` の自動処理は RFC 9110 準拠でコアが面倒を見る。

---

## 7. アプリケーション API(Context 設計)

### 7.1 ハンドラは `Context` を 1 つ受け取る(Hono 踏襲)

```python
@app.get("/todos/:id")
async def show(c: Context):
    todo = await repo.find(c.req.param("id"))
    return c.json(todo)                     # ヘルパー経由
    # return Response.json(todo) でも良い    # 生 Response も常に有効
```

- `c.req: Request`(+ `c.req.param()` / `c.req.query()` などサーバー側拡張)
- `c.env`: 実行環境バインディング(Workers の env / ASGI では lifespan state + 環境変数)。ジェネリクスで型付け
- `c.get()` / `c.set()`: ミドルウェア → ハンドラ間の型付き受け渡し(Hono の `c.var`)
- `c.header()`: レスポンスヘッダーの積み上げ
- `c.wait_until(coro)`: レスポンス返却後に完了を保証する後処理の登録。Workers の `ctx.waitUntil` に 1:1 対応し、ASGI ではレスポンス送信後のタスク実行にマップ(エッジ調査より昇格 → docs/research/cloudflare.md §3.4)
- ヘルパー: `c.json()` `c.text()` `c.html()` `c.body()` `c.redirect()` `c.not_found()`

**却下した代替案**:
- FastAPI 型のシグネチャ検査 + 引数注入 — 魔法が多く、実行パスが複数になる(単一経路原則違反)。バリデーションと DI をコアに引き込む重力が働くのも避けたい。
- 素の `handler(request) -> Response` 一本 — 最も標準純粋だが、ミドルウェアからの値受け渡しとレスポンスヘルパーの置き場がなくなり、実用 DX で Hono に遠く及ばない。なお `app.mount_fetch(handler)` で素の fetch ハンドラのマウントは可能にする(Workers 互換コードの受け入れ口)。

### 7.2 ミドルウェア: onion モデル

```python
@app.use
async def server_timing(c: Context, next):
    start = time.perf_counter()
    await next()
    dur = (time.perf_counter() - start) * 1000
    c.res.headers.append("server-timing", f"app;dur={dur:.1f}")
```

- `await next()` の前後に処理を書く Koa / Hono スタイル。`app.use(pattern, mw)` でパス限定適用。
- ミドルウェアもハンドラも同一シグネチャ側で正規化し、内部の実行機構は 1 本(合成された coroutine チェーン)。

### 7.3 標準添付ミドルウェア(バッテリー)

Hono のミドルウェア群に対応。すべてゼロ依存で書けるものから:

`logger` / `cors`(Fetch 標準の CORS 意味論) / `etag`(RFC 9110 条件付きリクエスト) / `compress`(gzip・deflate は stdlib、zstd は 3.14+ の `compression.zstd`、brotli は extra) / `basic_auth` / `bearer_auth` / `body_limit` / `timeout` / `secure_headers`(CSP, Sec-Fetch-* 検査) / `request_id`(W3C Trace Context) / `cache`(RFC 9111) / `trailing_slash`

JWT(HS256 は stdlib の hmac で可、RS256 等は `hayate-jwt` extra)のように暗号依存が出るものはコアから分離する。

---

## 8. 実行モデル(並行性)

| 論点 | 決定 | 理由 |
|---|---|---|
| 非同期基盤 | **asyncio のみ**(anyio 非依存) | ゼロ依存方針。内部で使うのは await / TaskGroup / timeout の最小サブセットなので、将来 anyio 対応が必要になっても表面 API は変わらない |
| sync ハンドラ | 許容し、登録時に検出して `asyncio.to_thread` 実行に**正規化**。ただし **ASGI 系アダプタ限定機能**(Pyodide にはスレッドがないため Workers では async ハンドラのみ) | 実行機構は coroutine チェーン 1 本のまま(単一経路)。free-threading 時代に価値が上がる |
| タイムアウト | `asyncio.timeout` ベースの `timeout` ミドルウェア | 標準機構の再利用 |
| キャンセル | `request.signal` ⇔ asyncio cancellation のブリッジ。既定は継続、opt-in で中断 | §4.5 |
| free-threading(3.13t/3.14t) | コアをグローバル可変状態ゼロで設計し、CI に free-threaded ビルドを含める | 「対応」は設計制約であって機能ではない |
| lifecycle | `app.on_start` / `app.on_stop`(ASGI lifespan にマップ) | Workers など lifespan のない環境ではアダプタが no-op |

---

## 9. 型付けとバリデーション

### 9.1 型付け

- Python 3.12+ を最低ラインとし、PEP 695 構文で書く。`Hayate[Env, Vars]` で env / 変数辞書を型付け。
- pyright / ty の strict モードを CI で強制。**「型が通らない API は設計が悪い」を原則にする**。
- TS の Hono が誇るパスパラメータのリテラル型推論(`/:id` → `{id: string}`)は Python の型システムでは不可能。**率直に諦めて**ドキュメントに明記し、実行時 validator(下記)に委ねる。中途半端な型スタブ生成などはしない。

### 9.2 バリデーション(コアに入れない)

Hono が zod をコアに入れなかったのと同じ判断。コアは**フックだけ**を持つ:

```python
from hayate.validator import validator
import msgspec

class BookIn(msgspec.Struct):
    title: str
    year: int

@app.post("/books", validator("json", BookIn))   # msgspec/pydantic アダプタは extra
async def create(c: Context):
    book = c.req.valid("json")                    # 検証済み・型付きの値
    ...
```

- `hayate-msgspec` / `hayate-pydantic` を別配布(コアのゼロ依存を守る)。
- 失敗時のレスポンスは RFC 9457 Problem Details + `errors` 拡張メンバー(§11)で統一。

---

## 10. HTTP 機能マップ(RFC → 提供形態)

| 機能 | 根拠標準 | 提供形態 |
|---|---|---|
| コンテントネゴシエーション | RFC 9110 §12 | `c.req.accepts(...)` ヘルパー |
| 条件付きリクエスト(ETag / If-None-Match) | RFC 9110 §13 | `etag` ミドルウェア |
| Range リクエスト | RFC 9110 §14 | 静的ファイルヘルパー(v0.2) |
| キャッシュ制御 | RFC 9111 | `cache` ミドルウェア + `CacheControl` ビルダー |
| Cookie(SameSite, `__Host-`) | RFC 6265bis | `c.req.cookies` / `c.set_cookie()`(HMAC 署名は opt-in) |
| 圧縮(gzip / zstd / brotli) | RFC 1952 / 8878 / 7932 | `compress` ミドルウェア |
| エラー表現 | RFC 9457 | `HTTPException` → `application/problem+json` |
| 構造化ヘッダー | RFC 9651 | `hayate.http.sfv` パース/シリアライズ |
| SSE | WHATWG HTML | `c.event_stream()`(async generator を返すだけ) |
| WebSocket | RFC 6455 | `app.ws()`(v0.2、WHATWG WebSocket API 形状) |
| 103 Early Hints | RFC 8297 | 将来。ASGI 拡張の普及を待つ |

## 11. エラー処理

```python
raise HTTPException(404, title="Book not found", detail=f"id={id} does not exist")
```

- 既定の直列化は **RFC 9457 Problem Details**(`application/problem+json`)。独自エラー JSON 形式を発明しない。
- `app.on_error(handler)` / `app.not_found(handler)` で上書き可能(Hono 互換)。
- 未捕捉例外は 500 + ログ。デバッグモード時のみトレースバックを含める。

## 12. マルチランタイム(アダプタ)

| ターゲット | 形態 | 備考 |
|---|---|---|
| ASGI(uvicorn / granian / hypercorn) | `app` 自体が ASGI callable(`__call__` がアダプタに委譲) | `uvicorn main:app` がそのまま動く。v0.1 の主力 |
| テスト | `await app.request(...)` | アダプタなしでコアを直接呼ぶ(§13) |
| Cloudflare Python Workers | `Default = to_workers(app)`(`WorkerEntrypoint` サブクラスを生成) | JS Request → hayate Request の 1 段変換で **fetch 直結**(公式推奨の FastAPI は ASGI 変換を挟む 2 段構成 — ここが差別化)。`env` は JsProxy を `c.env` に素通し、`ctx.waitUntil` は `c.wait_until()` にマップ。scheduled / Queues / Durable Objects は素の `workers` API と同居(Hono の `{ fetch: app.fetch, scheduled }` と同型)。ベータのため tier-2。詳細: docs/research/cloudflare.md |
| AWS Lambda(Function URL / API GW) | `handler = to_lambda(app)` | Mangum 相当を内蔵 |
| WSGI | **提供しない** | 同期世界への逆行。既存ブリッジで足りる |

コアがゼロ依存・純粋関数であることが、アダプタを「変換だけの薄い層」に保つ鍵。逆に言えば、コアに I/O や ASGI 概念が漏れた瞬間にこの表は崩れる。

## 13. テスト戦略

### 13.1 ユーザー向け: `app.request()`

```python
async def test_create_book():
    res = await app.request("/books", method="POST", json={"title": "SICP"})
    assert res.status == 201
    assert (await res.json())["title"] == "SICP"
```

サーバー起動もテストクライアントライブラリも不要(Hono の DX をそのまま輸入)。fetch モデルの直接的な配当。

### 13.2 フレームワーク自身の準拠テスト

- **wpt(web-platform-tests)の URLPattern / URL / Headers テストベクタをベンダリング**して CI で実行。「準拠している」を主張ではなく数値(pass rate)で示す。これが「標準準拠」を名乗る資格の担保。
- HTTP 意味論(405/Allow、HEAD、条件付きリクエスト等)は RFC の MUST 条項をテスト名に引用したテストスイートを作る。

## 14. パフォーマンス方針(2026-07-22 改訂: 理論限界を攻める)

目標を「Starlette 同等以上」から「**Fetch モデルを保った理論限界**」へ引き上げる。実測(docs/benchmarks.md): 素の ASGI 関数の床は 0.51µs/req、フレームワーク税は hayate/Starlette とも約 4.5µs。CPython はインタープリタであり、税はほぼ「オブジェクト生成数 + 関数呼び出し数 + バイトコード量」に線形 — 削る対象はこの 3 つ。

### 14.1 設計原則

1. **意味論は eager、実体化は lazy**: Fetch 標準は観測的意味論。`c.req.headers` が触られた瞬間に正しければ準拠であり、触られなかった Request 構成要素(Headers 実体・URL・signal・変数辞書)は作らない。
2. **起動時に計算できるものは起動時に**: ルートコンパイル、ミドルウェアチェーン合成、定数のエンコード。Pyodide のメモリスナップショットは起動時計算を**ランタイムコストゼロ**にするため、この原則は Workers で二重に効く。
3. **wire-native 内部表現**: サーバーは bytes を渡してくる。公開 API は Fetch の文字列意味論を維持し、内部は bytes を保持して**境界で遅延変換**する(ASGI はヘッダー名の小文字化を保証しており再正規化も不要)。

### 14.2 3 層アーキテクチャ

| Tier | 内容 | 動作環境 |
|---|---|---|
| 0: 参照実装 | pure Python。意味論の正であり、全機能のフォールバック | 全環境(Pyodide 含む) |
| 1: 内部最適化 | 遅延実体化・bytes 内部表現・事前合成(Tier 0 と同一コードベース) | 全環境 |
| 2: native accelerator | Rust(maturin)による **opt-in** 拡張(`accel/` = `hayate-accel`)。初弾は compact JSON encoder(dynamic-json を 0.99x → 1.22x に改善)。次候補は計測で選定(multipart、SFV) | native CPython(abi3 wheel、pyo3 0.26)。**Workers は PyEmscripten wheel をサポートするため、emscripten ターゲットもビルドできれば Pyodide でも有効** |

Tier 2 の受け入れ条件: ① pure Python フォールバックと挙動同一(同一テストスイートを両実装で実行)、② 意味論コードと加速コードの分離、③ Pyodide の 6 ヶ月ごとの ABI 追随コストを負えること。デメリット(ビルドチェーン複雑化・デバッグ困難化・供給網リスク)は①②で封じ込める。

### 14.3 JIT との関係

- CPython 3.13+ の copy-and-patch JIT は実験的・デフォルト無効で、**Pyodide(WASM)では実行時マシンコード生成が原理的に不可**。「JIT 前提の設計」は Cloudflare 対応と正面衝突するため採らない。
- 代わりに **specializing adaptive interpreter(PEP 659、3.11+ で常時有効、Pyodide でも効く)前提**をコーディング規約とする: 呼び出しサイトの単相化、ホットパスの型安定、動的分岐の削減。この規約は将来 JIT が既定化したときそのまま JIT に有利に働く。
- ベンチ体制: 床(素の ASGI)との差 =「フレームワーク税」を主指標とし、リグレッションを CI で検出する。

## 15. リポジトリ構成とツールチェーン

```
hayate/
  pyproject.toml          # uv + hatchling, PEP 621
  src/hayate/
    __init__.py           # Hayate, Context, Request, Response, HTTPException
    request.py  response.py  headers.py  url.py  urlpattern.py
    context.py  router.py  app.py
    http/                 # sfv.py, cookies.py, negotiation.py など RFC 実装
    middleware/           # logger.py, cors.py, etag.py, compress.py, ...
    adapters/             # asgi.py, workers.py, aws.py
    testing.py
  tests/
    wpt/                  # ベンダリングした wpt テストベクタ
  docs/
```

- ツール: uv / ruff(lint + format)/ pyright or ty(strict)/ pytest / GitHub Actions(3.12–3.14 + free-threaded)
- **言語ポリシー(決定)**: 公開ドキュメント・README・docstring・コード内コメントは**英語を第一言語**とする(OSS として国際的に使われることを想定)。本書のような内部設計メモは日本語で良い。
- ライセンス: MIT(Hono と同じ)を推奨

## 16. スコープ外(YAGNI リスト)

v1 まで**やらない**と明示するもの:

| やらないこと | 理由 |
|---|---|
| テンプレートエンジン / JSX 相当 | `c.html()` に文字列を渡せば足りる。API ファースト |
| ORM / DB 統合 / DI コンテナ | フレームワークの仕事ではない |
| fetch クライアント(`hayate.fetch()`) | サーバー側が先。需要(BFF / プロキシ用途)の証拠が出たら検討 |
| OpenAPI 自動生成 | validator エコシステムが固まる v0.3 以降に判断 |
| SmartRouter / 複数ルーター | 単一実装で十分(§6.2) |
| WSGI アダプタ / Python 3.11 以前 | 過去との互換はこのプロジェクトの目的に無い |
| HTTP/2 Server Push | 標準側で事実上廃止済み |

## 17. リスクと対応

| リスク | 対応 |
|---|---|
| WHATWG URL / URLPattern 完全準拠の泥沼(仕様が巨大) | 「実用部分集合」を最初に明文化し、wpt pass rate を公開して準拠範囲を誠実に示す |
| 性能で Rust 系に見劣り | 土俵を明示(§1.3)。Starlette 同等を CI で担保 |
| 「snake_case は標準じゃない」批判 | §5 の対応表と設計原則文書で先回りして立場を宣言 |
| Python Workers がベータのまま停滞 | 2025 年時点で DO / Workflows / scheduled の Python 対応、メモリスナップショットで cold start 10 倍改善と進展は前向き(docs/research/cloudflare.md)。それでも Workers アダプタは tier-2 とし、コア価値(ASGI + テスト DX + 標準準拠)は単独で成立する設計にしてある |
| PyPI 名 `hayate` が公開前に第三者に取られる | private 開始のため公開まで名前を確保できない(PyPI は placeholder 登録を規約で禁止)。v0.1 が形になり次第、最小実装で早期に 0.0.x を公開して確保する |

## 18. 決定事項・マイルストーン・未決事項

### 決定済み(2026-07-22)

| 項目 | 決定 |
|---|---|
| 名前 | **hayate**(疾風)。配布名 = import 名 = `hayate`、アプリクラスは `Hayate`。GitHub リポジトリも `haya-inc/para` → `haya-inc/hayate` へのリネームを推奨 |
| ドキュメント言語 | **英語先行**(公開ドキュメント・README・docstring・コード内コメント)。内部設計メモは日本語可 |
| 公開戦略 | **private で開始**。v0.1 完成時に公開(PyPI 名確保を兼ねる)を判断 |
| 最低 Python | **3.12**(PEP 695 対応と採用の広さのバランス。Pyodide 現行の 3.12/3.13 系とも整合) |

### マイルストーン

| 版 | 内容 | 受け入れ基準 |
|---|---|---|
| **v0.1 コア** | Headers → URL/URLSearchParams → URLPattern → Request/Response → Context/Router/App → ASGI アダプタ → testing → 初期ミドルウェア(logger, cors, etag, basic_auth, compress) | TODO API がテスト付きで書ける。wpt サブセット合格。Starlette 比ベンチ公開 |
| **v0.2** | SSE / WebSocket / secure_headers / 署名 cookie / body_limit / timeout / 静的ファイル(Range, 304, 416)/ cache(マイクロキャッシュ + Cache-Control/Age)— **すべて実装済み** | リアルタイムチャットのサンプルが動く ✅(examples/chat.py + tests/test_chat_example.py) |
| **v0.3** | validator フック(実装済み — callable プロトコルにより msgspec / pydantic が**アダプタパッケージなしで直結**、専用 extra は YAGNI で不要と判明)/ Workers アダプタ(実装済み、モックテスト済み)/ Lambda アダプタ(実装済み、API GW v2.0)/ ドキュメントサイト(未) | 同一アプリが uvicorn と Workers で無変更動作 — 残タスクは Pyodide 実機検証(docs/research/cloudflare.md §5)とストリーミングブリッジ |
| v1.0 | API 凍結、OpenAPI 等は証拠駆動で判断 | — |

### 未決事項(要判断)

現時点でなし。次の判断ポイントは v0.1 完成時の「公開タイミング」(§17 の PyPI 名確保と連動)。
