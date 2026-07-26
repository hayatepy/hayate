#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test_dir="$(mktemp -d)"
log_file="${test_dir}.workerd.log"
dry_run_log="${test_dir}.dry-run.log"
bundle_dir="${test_dir}/bundle"
port=8791
server_pid=""

terminate_tree() {
  local parent_pid="$1"
  local child_pid
  while read -r child_pid; do
    if [[ -n "${child_pid}" ]]; then
      terminate_tree "${child_pid}"
    fi
  done < <(pgrep -P "${parent_pid}" 2>/dev/null || true)
  kill "${parent_pid}" 2>/dev/null || true
}

cleanup() {
  if [[ -n "${server_pid}" ]] && kill -0 "${server_pid}" 2>/dev/null; then
    terminate_tree "${server_pid}"
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

mkdir -p "${test_dir}/src"
cp "${repo_dir}/examples/workers/src/entry.py" "${test_dir}/src/entry.py"
cp "${repo_dir}/examples/workers/wrangler.toml" "${test_dir}/wrangler.toml"
sed \
  "s|\"hayate>=0.11.1\"|\"hayate @ file://${wheel_path}\"|" \
  "${repo_dir}/examples/workers/pyproject.toml" >"${test_dir}/pyproject.toml"

(
  cd "${test_dir}"
  uvx --from workers-py==1.15.0 pywrangler sync
)

test -e "${test_dir}/python_modules/uts46"

(
  cd "${test_dir}"
  uvx --from workers-py==1.15.0 pywrangler deploy \
    --dry-run \
    --outdir "${bundle_dir}"
) >"${dry_run_log}" 2>&1

upload_size="$(grep -F "Total Upload:" "${dry_run_log}" | tail -1)"
if [[ -z "${upload_size}" ]]; then
  cat "${dry_run_log}"
  echo "Wrangler dry-run did not report an upload size" >&2
  exit 1
fi
echo "upload[core-workers]=${upload_size}"

for excluded_path in \
  "python_modules/asgi.py" \
  "python_modules/hayate/adapters/asgi.py" \
  "python_modules/hayate/adapters/aws.py" \
  "python_modules/workers/wsgi.py"; do
  if [[ -e "${bundle_dir}/${excluded_path}" ]]; then
    echo "excluded path reached Wrangler upload: ${excluded_path}" >&2
    exit 1
  fi
done
if find "${bundle_dir}" -type d -name "*.dist-info" -print -quit | grep -q .; then
  echo "package metadata reached Wrangler upload" >&2
  exit 1
fi
if find "${bundle_dir}" \( -type f -name "*.pyc" -o -type d -name "__pycache__" \) \
  -print -quit | grep -q .; then
  echo "Python cache reached Wrangler upload" >&2
  exit 1
fi
if [[ ! -f "${bundle_dir}/python_modules/uts46/_data.py" ]]; then
  echo "required UTS-46 mapping is absent from Wrangler upload" >&2
  exit 1
fi

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
