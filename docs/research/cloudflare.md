# 調査: Cloudflare 最新機能 × hayate(2026-07-22)

> 目的: Hono が Cloudflare エコシステムで享受している統合を、Python(hayate)でどこまで再現できるかを確認する。
> 結論を先に: **できる。しかも hayate の設計(最小 pure-Python 依存・fetch 直結)は Python Workers の制約下でむしろ優位に働く。** ただしベータ由来の条件がいくつかある(§4)。

## 1. Python Workers の現状(2026 年時点)

- **実行基盤**: Pyodide(CPython の WebAssembly 移植)を workerd が直接ホスト。`python_workers` 互換性フラグが必要な**ベータ**。Pyodide バージョンは 6 ヶ月ごとに更新され、compatibility date で固定される。
- **cold start**: デプロイ時に top-level import まで実行した**メモリスナップショット**を取り、起動時に復元する方式で約 10 倍改善(2025-12)。httpx + fastapi + pydantic 込みで約 1.0 秒(Lambda 同等構成の 2.4 倍速)。「ゼロ cold start」がロードマップに載っている。ただし JS Workers の数 ms には届いていない。
- **パッケージ**: `pyproject.toml` に依存を書き、`uv run pywrangler dev / deploy`(uv 統合の専用ツール)でバンドル。**pure Python wheel と Pyodide ビルド済みパッケージのみ**。任意の C 拡張は不可。依存はバンドルサイズに直結。
- **本番デプロイ**: パッケージ込みのデプロイが可能になった(以前は built-in のみ・ローカル限定だった)。
- **エントリポイント**: `WorkerEntrypoint` クラスのメソッドとして定義する:

```python
from workers import WorkerEntrypoint, Response

class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return Response("Hello world!")
```

## 2. 機能マトリクス: Hono(JS)との比較

| Cloudflare 機能 | Hono / JS | Python Workers | hayate での扱い |
|---|---|---|---|
| fetch ハンドラ | ✅ | ✅ `WorkerEntrypoint.fetch` | `Default = to_workers(app)` がクラスを生成 |
| KV / R2 / D1 / Queues 送信 / Workers AI / Vectorize / Hyperdrive | ✅ `c.env` | ✅ `self.env.*`(FFI 経由、JS Promise はそのまま `await` 可能) | `c.env` に JsProxy を素通し。`await c.env.KV.get("k")` がそのまま動く |
| Durable Objects(クラス定義) | ✅ | ✅ **`from workers import DurableObject` で Python でも書ける** | コアはスコープ外。DO の `fetch` に hayate app をマウントするパターンは可能 |
| scheduled(cron) | ✅ | ✅ `async def scheduled(self, controller, env, ctx)` | アダプタ対象外。ユーザーが `WorkerEntrypoint` に直接書き、fetch だけ hayate に委譲(Hono の `export default { fetch: app.fetch, scheduled }` と同型) |
| Queues 消費(consumer) | ✅ | ✅ WorkerEntrypoint のハンドラとして定義 | 同上 |
| Workflows(durable execution) | ✅ | ✅ **Python Workflows ベータあり**(`@step.do` デコレータ形式、DO の上に構築) | hayate と独立に併用可能 |
| Agents SDK | ✅ | ❌ JS のみ | 対象外(将来の観察項目) |
| WebSocket / DO hibernation | ✅ | FFI 経由で理論上可、公式例が薄い | v0.2 の WebSocket 設計時に実機検証 |
| Static Assets / Smart Placement / VPC Services / Containers バインド | ✅ | 設定側の機能 or env バインドで言語非依存 | 関与不要(そのまま使える) |

**Hono にあって Python に無いもの**は Agents SDK と「数 ms の cold start」の 2 つが本質。それ以外の主要機能は 2025 年の進展(DO・Workflows・scheduled の Python 対応)でほぼ埋まっている。

## 3. hayate 設計への含意

### 3.1 最小 pure-Python 依存が Workers で武器になる

- バンドルに入るのは hayate と約190 KiB・推移依存なしの `uts46`。スナップショットのサイズ・復元時間・128MB メモリ制限への影響を限定する。
- Cloudflare 公式推奨の FastAPI スタック(fastapi + pydantic + starlette)と比べ、依存グラフが桁違いに小さい。**「Workers 上で最軽量の Python フレームワーク」**のポジションが空いている。

### 3.2 fetch 直結の構造的優位

公式の FastAPI 統合は「JS Request → ASGI scope/receive/send 変換 → Starlette の独自 Request」という 2 段変換。hayate は「JS Request → hayate Request」の 1 段で、概念モデルも Fetch のまま:

```
FastAPI:  JS Request → [ASGI 変換] → ASGI scope → Starlette Request   (2 変換 + プロトコル切替)
hayate:   JS Request → hayate Request                                  (1 変換、同一概念)
```

Hono が Node で「独自 req/res への変換を挟まない」ことで得た優位と同じ構図が、Python Workers 上で再現できる。

### 3.3 Workers アダプタの設計スケッチ

```python
# main.py(Workers エントリ)
from hayate.adapters.workers import to_workers
from app import app

Default = to_workers(app)   # WorkerEntrypoint サブクラスを生成
```

変換層の責務(すべて薄い):
- **JS Request → hayate Request**: method / url / headers は JsProxy から読み取り。body は JS ReadableStream → `AsyncIterable[bytes]` ブリッジ(Pyodide の JsProxy async iteration)
- **hayate Response → JS Response**: status / headers / body(`AsyncIterable[bytes]` → JS ReadableStream)
- **`self.env`**: 変換せず `c.env` に素通し(JsProxy のまま。バインディングの網羅的ラッパーは作らない — YAGNI、Cloudflare の API 追随コストを負わない)
- **`self.ctx.waitUntil`**: `c.wait_until()` にマップ(§3.4)
- **AbortSignal**: JS の `request.signal` → hayate `AbortSignal` ブリッジ

### 3.4 設計変更: `c.wait_until()` を Context 標準 API に追加

レスポンス返却後の後処理(ログ送信、キャッシュ書き込み等)はエッジでは `ctx.waitUntil` が唯一の手段。ASGI でも「レスポンス送信後にタスク実行」として自然に実装できるため、**Context の標準 API に昇格させる**(DESIGN.md §7.1 に反映済み)。

### 3.5 制約の追認と調整

- **async-first の追認**: Python Workers は async I/O のみ(`requests` 不可、httpx/aiohttp の async のみ)。hayate の async-first 方針と完全一致。
- **sync ハンドラは ASGI 限定機能に**: Pyodide にはスレッドがなく `asyncio.to_thread` が使えない。sync ハンドラ許容(DESIGN.md §8)は「ASGI 系アダプタ限定」と明記(反映済み)。
- **zstd 圧縮**: Pyodide の Python バージョン依存。既定の「3.14+ なら有効」の条件分岐で対応済み、変更不要。

## 4. できないこと・条件付きのこと(制約リスト)

1. **ベータ**: `python_workers` フラグ必須。SLA なし。本番採用は顧客要件次第で判断
2. **パッケージ制約**: pure Python + Pyodide ビルド済みのみ。ユーザーアプリの依存選定に影響(hayate の唯一の依存 `uts46` は pure Python)
3. **メモリ 128MB** を Pyodide ランタイムと共有
4. **cold start ~1 秒級**: 10 倍改善後もレイテンシ敏感な用途では JS(Hono)に分がある
5. **生 TCP / socket 不可**: DB 直結は Hyperdrive / D1 / HTTP 系 API 経由(native TCP binding はロードマップ言及あり)
6. **Agents SDK は JS のみ**
7. **Pyodide の Python バージョンは選べない**(compatibility date で間接指定)→ hayate の 3.12+ 要件は Pyodide 現行(3.12/3.13 系)と整合

## 5. Workers 実機検証リスト(2026-07-22 更新: 全項目検証完了 — ローカル workerd + Cloudflare 本番)

検証環境: `examples/workers/` + `pywrangler dev`(workers-py 1.15 / wrangler、ローカル workerd)。
GET / ルートパラメータ / 404 `application/problem+json` / 405 + `Allow` がすべて期待どおり動作。

- [x] Pyodide 上で hayate コアの import・起動 — 問題なし(hayate 0.3.1 を PyPI wheel から vendor して動作)
- [x] 実ランタイムの FFI 形状 — **workerd は workers-py の Python Request ラッパー(`bytes()` / `headers.items()`)を渡す**。raw JsProxy(`arrayBuffer()` / `entries()`)とは別形状。両対応に修正(0.3.1)し回帰テストで固定。モックだけでは検出不能だった
- [x] `pywrangler` との相性 — pywrangler は pylock.toml(PyPI 解決)から `python_modules/` に vendor するため、`tool.uv.sources` の path 依存は**反映されない**。ローカル変更の実機検証は PyPI リリース経由が確実
- [x] JS ReadableStream ↔ `AsyncIterable[bytes]` ブリッジ — **実機検証済み(hayate 0.3.2、2026-07-22)**。`/events`(SSE、0.5s 間隔 ×3)で **TTFB 3ms / 総時間 1.51s** を計測 — バッファリングなら両者がほぼ一致するため、逐次配信の実証。`/stream`(チャンク応答)と `/echo`(リクエストボディの FFI 越し受信)も期待どおり。実装メモ: レスポンス側は `ReadableStream.from()` + チャンクを `to_js` で `Uint8Array` 化(`from` は workerd では compat flag なしの常時有効 — `readable.h` の `JSG_STATIC_METHOD(from)` で確認)。workers SDK の `Response` は `RESPONSE_ACCEPTED_TYPES` に `"ReadableStream"` を含むため body に直接渡せる。リクエスト側は `getReader()` ループ。部品が無い環境ではバッファリングへフォールバック
- [x] JS AbortSignal → hayate AbortSignal ブリッジ — **配線を実機確認(0.3.2)**: SSE を途中切断してもサーバーは健全(直後のリクエストに 200)・ログにエラーなし。ラッパー Request は `signal` を持たず、生 JS Request を保持する `js_object` 経由でのみ到達できる(SDK ソースで確認)。リスナーは `create_proxy` で保持(暗黙変換だと呼び出し終了時に破棄される)。**解決(0.4.0)**: FinalizationRegistry(エンジンは実行を保証しない)には頼らず、リクエスト終了時に決定的に破棄する設計へ変更 — abort リスナーは `removeEventListener` + `destroy()`、応答 generator の proxy は完了翌 tick で `destroy()`、WS リスナー 3 種は接続終了時に破棄。実測: 3,200 リクエスト(SSE 途中切断 400・WS 接続サイクル 400 含む)で workerd RSS **35.4 → 35.9 MB**・ログエラー 0 — 成長傾向なし
- [x] DO の fetch に hayate app をマウントするパターンの成立性 — **実機検証済み(hayate 0.4.0、2026-07-22、ローカル + 本番)**。`@to_durable_object` デコレータ(`factory(ctx, env) -> Hayate`、Hono のコンストラクタ内クロージャキャプチャと同型)で成立。**罠**: workerd はエントリモジュールの属性名ではなく **`cls.__name__` で DO クラスを登録**する(workerd `introspection.py` の `collect_entrypoint_classes` が `{"className": attr.__name__}` を返す)ため、factory 名 = wrangler.toml の `class_name` にする必要がある(`to_workers` が動いていたのは内部クラス名がたまたま `Default` だったから)。呼び出し側は `env.BINDING.getByName(name)` → `stub.fetch(url)`(SDK の `_DurableObjectNamespaceWrapper` → `_FetcherWrapper`)。無料プランは `new_sqlite_classes` マイグレーションが必須。名前ごとの独立カウンタが本番でも永続することを確認(デプロイ直後、新規オブジェクトの初回タッチで一過性の Cloudflare error 1042 を 1 回観測 — 再試行で解消、以後再現せず)
- [x] WebSocket upgrade の API 形状 — **実機検証済み(0.4.0、ローカル + 本番 wss)**。`client, server = WebSocketPair.new().object_values()` → `server.accept()` → `workers.Response(None, status=101, web_socket=client)`(SDK が `web_socket` kwarg をネイティブサポート — `_create_options` が `webSocket` に転記)。ハンドラは ASGI と完全同一の `@app.ws()` / `WebSocket` API のまま: JS イベントを asyncio.Queue で ASGI 形式メッセージにブリッジする receive/send シムを渡すだけ。**罠 2 つ**: (1) workerd のバイナリフレームは既定で **`Blob`**(同期読み出し不可)— accept 直後に `binaryType = "arraybuffer"` を設定して解決(WHATWG の settable 属性)。(2) ArrayBuffer proxy は TypedArray と違い **`to_py()` で変換されない** — JsBuffer API の `to_bytes()` を優先(SDK 自身も `request.py` で同じ手法)。テキスト/バイナリ echo・サーバー起点クローズ(1000)・ハンドラ例外時 1011 を本番 wss で確認。DO 内の WS ルートも同一コードパス(共通 `_handle_fetch`)で動作。hibernation API(`state.acceptWebSocket` + `webSocketMessage`)は標準外のプラットフォーム拡張のため未使用 — 必要になったら証拠駆動で検討
- [x] Cloudflare 本番へのデプロイ — **完了(2026-07-22、`pywrangler deploy`、hayate 0.4.0 を PyPI から vendor)**: https://hayate-example.yusuke8h.workers.dev。Worker Startup Time 940 ms、cold start 実測 ~1.6 s、warm SSE **TTFB 53 ms / 総時間 1.55 s**(本番エッジでも真の逐次配信)。GET / ルートパラメータ / 404 problem+json / 405 + Allow / POST echo / SSE / WebSocket(wss)/ DO カウンタ永続、すべて期待どおり
- [x] **outer app → DO への `forward()` が POST ボディを運ぶか** — **検証済み(2026-07-23、ローカル workerd、最小 repro)**。従来 §5 は GET forward のみ検証だったため hayate-mcp v0.2 の DO 化で疑義が生じ、最小 DO(`@to_durable_object`)へ `forward(c, stub)` で POST(JSON body)を転送する repro を作成 → **DO 側で `await c.req.json()` が期待どおり body を受信**。`getByName(name)` / `get(newUniqueId())` / `get(idFromString(idstr))` の 3 経路すべてで POST 成立(DO は `ctx.id.toString()` で自身の id を報告 → outer が `idFromString` で往復可能)。**結論: POST-body DO forward は成立**。hayate-mcp 側の DO 未達は別要因(mcp SDK の anyio `Server` を DO 内で走らせる経路 / vendor バンドル汚染)に切り分けられた

## 6. 情報源

- [Write Cloudflare Workers in Python](https://developers.cloudflare.com/workers/languages/python/)(ベータ、対応バインディング一覧)
- [Python packages in Workers](https://developers.cloudflare.com/workers/languages/python/packages/)(pyproject.toml / pywrangler / 対応パッケージ)
- [How Python Workers work](https://developers.cloudflare.com/workers/languages/python/how-python-workers-work/)(Pyodide、スナップショット、バージョン管理)
- [Python Workers FFI](https://developers.cloudflare.com/workers/languages/python/ffi/)(js モジュール、to_js、バインディング呼び出し)
- [workers SDK ソース(`_workers.py`)](https://github.com/cloudflare/workerd/blob/main/src/pyodide/internal/workers-api/src/workers/_workers.py)(ラッパー Request/Response の正確な形状: `js_object`、`body`、`RESPONSE_ACCEPTED_TYPES`。`signal` プロパティは存在しない)
- [workerd `readable.h`](https://github.com/cloudflare/workerd/blob/main/src/workerd/api/streams/readable.h)(`ReadableStream.from` が `JSG_STATIC_METHOD` として無条件登録)
- [Python Workers examples](https://developers.cloudflare.com/workers/languages/python/examples/)(fetch / scheduled / DO / D1 / Queues のコード例)
- [Python Workers redux: fast cold starts, packages, and a uv-first workflow](https://blog.cloudflare.com/python-workers-advancements/)(2025-12 の大幅改善)
- [A closer look at Python Workflows](https://blog.cloudflare.com/python-workflows/)(Python Workflows ベータ)
- [InfoQ: Python Workers Redux — Wasm Snapshots and Native uv Tooling](https://www.infoq.com/news/2025/12/cloudflare-wasm-python-snapshot/)
- [Containers are coming to Cloudflare Workers](https://blog.cloudflare.com/cloudflare-containers-coming-2025/) / [Workers VPC](https://developers.cloudflare.com/workers-vpc/) / [Cloudflare Agents](https://developers.cloudflare.com/agents/)(周辺の 2025-2026 新機能)
