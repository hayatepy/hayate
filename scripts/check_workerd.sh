#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test_dir="$(mktemp -d)"
log_file="${test_dir}.workerd.log"
port=8791
server_pid=""

cleanup() {
  if [[ -n "${server_pid}" ]] && kill -0 "${server_pid}" 2>/dev/null; then
    kill "${server_pid}" 2>/dev/null || true
    wait "${server_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# Pyodide's interpreter launcher needs this flag. Node 24 supports it;
# Node 26 removed it, so CI intentionally pins 24.
node --experimental-wasm-stack-switching --version >/dev/null

uv build --wheel --out-dir "${test_dir}/dist"
wheel_path="$(find "${test_dir}/dist" -name '*.whl' -print -quit)"
test -n "${wheel_path}"

cp "${repo_dir}/examples/workers/entry.py" "${test_dir}/entry.py"
cp "${repo_dir}/examples/workers/wrangler.toml" "${test_dir}/wrangler.toml"
sed \
  "s|\"hayate>=0.10.0\"|\"hayate @ file://${wheel_path}\"|" \
  "${repo_dir}/examples/workers/pyproject.toml" >"${test_dir}/pyproject.toml"

(
  cd "${test_dir}"
  uvx --from workers-py==1.15.0 pywrangler sync
)

test -e "${test_dir}/python_modules/uts46"

(
  cd "${test_dir}"
  uvx --from workers-py==1.15.0 pywrangler dev --port "${port}"
) >"${log_file}" 2>&1 &
server_pid=$!

ready=false
for _ in {1..60}; do
  if curl --fail --silent --max-time 2 "http://127.0.0.1:${port}/" >/dev/null; then
    ready=true
    break
  fi
  if ! kill -0 "${server_pid}" 2>/dev/null; then
    cat "${log_file}"
    exit 1
  fi
  sleep 1
done
if [[ "${ready}" != true ]]; then
  cat "${log_file}"
  exit 1
fi

canonical="$(
  curl --fail --silent --max-time 5 "http://127.0.0.1:${port}/canonicalize"
)"
python -c \
  'import json,sys; assert json.loads(sys.argv[1]) == {"hostname":"xn--wgv71a119e.example"}' \
  "${canonical}"
