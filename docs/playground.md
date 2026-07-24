# Playground

hayate and its single standards dependency are pure Python, so they run under
[Pyodide](https://pyodide.org) — **this page installs the real `hayate`
wheel from PyPI into your browser and runs it**. No server anywhere.

Edit the code and press **Run**. The first run downloads the Python runtime
(~10 MB); after that it's instant.

<textarea id="pg-code" spellcheck="false" style="width:100%;height:22em;font-family:var(--md-code-font-family,monospace);font-size:.85em;padding:.8em;border:1px solid var(--md-default-fg-color--lightest);border-radius:.2em;background:var(--md-code-bg-color);color:var(--md-code-fg-color);">
from hayate import Hayate, HTTPException

app = Hayate()

BOOKS = {"1": {"id": "1", "title": "SICP"}}

@app.get("/books/:id")
async def show(c):
    book = BOOKS.get(c.req.param("id"))
    if book is None:
        raise HTTPException(404, title="Book not found")
    return c.json(book)

res = await app.request("/books/1")
print(res.status, await res.text())

missing = await app.request("/books/9")
print(missing.status, await missing.text())
</textarea>

<p>
<button id="pg-run" class="md-button md-button--primary">Run in your browser</button>
</p>

<pre id="pg-out" style="min-height:6em;white-space:pre-wrap;"></pre>

<script type="module">
const btn = document.getElementById("pg-run");
const out = document.getElementById("pg-out");

async function ensurePyodide() {
  if (window._hayatePyodide) return window._hayatePyodide;
  out.textContent = "Loading Pyodide (first run only)...";
  const { loadPyodide } = await import("https://cdn.jsdelivr.net/pyodide/v0.28.2/full/pyodide.mjs");
  const pyodide = await loadPyodide();
  out.textContent += "\nInstalling hayate from PyPI...";
  await pyodide.loadPackage("micropip");
  const micropip = pyodide.pyimport("micropip");
  await micropip.install("hayate");
  window._hayatePyodide = pyodide;
  return pyodide;
}

btn.addEventListener("click", async () => {
  btn.disabled = true;
  try {
    const pyodide = await ensurePyodide();
    out.textContent = "";
    pyodide.setStdout({ batched: (line) => { out.textContent += line + "\n"; } });
    pyodide.setStderr({ batched: (line) => { out.textContent += line + "\n"; } });
    await pyodide.runPythonAsync(document.getElementById("pg-code").value);
  } catch (error) {
    out.textContent += "\n" + String(error);
  } finally {
    btn.disabled = false;
  }
});
</script>

!!! note "Why this works"
    The playground is not a demo build. `micropip.install("hayate")` fetches
    the same `py3-none-any` wheel from PyPI that servers use; `micropip`
    resolves its single pure-Python UTS-46 dependency too. That portable wheel
    set is also what makes hayate run on Cloudflare Python Workers.
