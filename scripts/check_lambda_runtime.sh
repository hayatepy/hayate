#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work_dir="$(mktemp -d)"
container_name="hayate-lambda-runtime-${PPID}-${RANDOM}"
image_name="hayate-lambda-runtime:${PPID}-${RANDOM}"

cleanup() {
  docker rm -f "${container_name}" >/dev/null 2>&1 || true
  docker image rm "${image_name}" >/dev/null 2>&1 || true
  rm -r "${work_dir}"
}
trap cleanup EXIT

uv build --wheel --out-dir "${work_dir}"
uv run --with pip python -m pip download \
  --only-binary=:all: \
  --require-hashes \
  --dest "${work_dir}" \
  --requirement "${repo_dir}/examples/lambda/requirements.lock" >/dev/null
cp "${repo_dir}/examples/lambda/Dockerfile" "${work_dir}/Dockerfile"
cp "${repo_dir}/examples/lambda/app.py" "${work_dir}/app.py"

docker buildx build \
  --load \
  --provenance=false \
  --tag "${image_name}" \
  "${work_dir}" >/dev/null
docker run --detach --rm \
  --name "${container_name}" \
  --publish 127.0.0.1::8080 \
  "${image_name}" >/dev/null

host_port="$(
  docker port "${container_name}" 8080/tcp |
    sed -n '1s/.*://p'
)"
if [[ -z "${host_port}" ]]; then
  echo "could not resolve the local Lambda Runtime Interface Emulator port" >&2
  exit 1
fi
endpoint="http://127.0.0.1:${host_port}/2015-03-31/functions/function/invocations"

for attempt in $(seq 1 30); do
  if curl \
    --fail \
    --silent \
    --output /dev/null \
    --header "content-type: application/json" \
    --data '{"version":"0"}' \
    "${endpoint}"; then
    break
  fi
  if [[ "${attempt}" = 30 ]]; then
    docker logs "${container_name}" >&2
    exit 1
  fi
  sleep 1
done

uv run python "${repo_dir}/scripts/check_lambda_runtime.py" "${endpoint}"
echo "AWS Lambda Python 3.14 packaged-runtime profile passed"
