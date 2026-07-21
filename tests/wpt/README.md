# Vendored web-platform-tests data

Test vectors from [web-platform-tests](https://github.com/web-platform-tests/wpt)
(BSD 3-Clause License), pinned to the commits below. Retrieved 2026-07-22.

| File | Source path | Pinned commit |
|---|---|---|
| `urlpatterntestdata.json` | `urlpattern/resources/` | `23aac9278460a73394585ff5a15b6a04dfcd5ec8` |
| `urltestdata.json` | `url/resources/` | `181476aa16e8b28a07698bef3a0275fa53dd22e5` |

To update, re-run:

```sh
SHA=$(curl -s "https://api.github.com/repos/web-platform-tests/wpt/commits?path=<SOURCE_PATH>/<FILE>&per_page=1" | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['sha'])")
curl -sf -o tests/wpt/<FILE> "https://raw.githubusercontent.com/web-platform-tests/wpt/${SHA}/<SOURCE_PATH>/<FILE>"
```

then update the pinned commit here and re-baseline the ratchet floors in
`tests/test_wpt_url.py` / `tests/test_wpt_urlpattern.py`.

Runners: `tests/test_wpt_urlpattern.py`, `tests/test_wpt_url.py`.
Measured results: `docs/conformance.md`.
