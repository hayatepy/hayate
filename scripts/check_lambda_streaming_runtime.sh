#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work_dir="$(mktemp -d)"
container_name="hayate-lambda-streaming-${PPID}-${RANDOM}"
runtime_name="hayate-lambda-streaming-runtime-${PPID}-${RANDOM}"
probe_name="hayate-lambda-streaming-probe-${PPID}-${RANDOM}"
network_name="hayate-lambda-streaming-${PPID}-${RANDOM}"
image_name="hayate-lambda-streaming:${PPID}-${RANDOM}"

cleanup() {
  docker rm -f "${container_name}" >/dev/null 2>&1 || true
  docker rm -f "${runtime_name}" >/dev/null 2>&1 || true
  docker rm -f "${probe_name}" >/dev/null 2>&1 || true
  docker network rm "${network_name}" >/dev/null 2>&1 || true
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
cp "${repo_dir}/examples/lambda-streaming/Dockerfile" "${work_dir}/Dockerfile"
cp "${repo_dir}/examples/lambda-streaming/app.py" "${work_dir}/app.py"
cp "${repo_dir}/examples/lambda-streaming/bootstrap.py" "${work_dir}/bootstrap.py"
cp "${repo_dir}/examples/lambda-streaming/entry.sh" "${work_dir}/entry.sh"

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

uv run python "${repo_dir}/scripts/check_lambda_streaming_runtime.py" "${endpoint}"

# The RIE invocation endpoint intentionally presents the completed invocation
# payload. Connect the same packaged runtime to a wire-level Runtime API probe
# to prove that its first body chunk arrives before the delayed second chunk.
docker rm -f "${container_name}" >/dev/null
docker network create "${network_name}" >/dev/null
docker run --detach \
  --name "${probe_name}" \
  --network "${network_name}" \
  --entrypoint /var/lang/bin/python3.14 \
  --volume "${repo_dir}/scripts/check_lambda_streaming_runtime_api.py:/tmp/runtime-api.py:ro" \
  "${image_name}" \
  /tmp/runtime-api.py >/dev/null

for attempt in $(seq 1 30); do
  if docker logs "${probe_name}" 2>&1 | grep --quiet "Runtime API probe ready"; then
    break
  fi
  if [[ "${attempt}" = 30 ]]; then
    docker logs "${probe_name}" >&2
    exit 1
  fi
  sleep 1
done

docker run --detach \
  --name "${runtime_name}" \
  --network "${network_name}" \
  --env AWS_LAMBDA_RUNTIME_API="${probe_name}:9001" \
  "${image_name}" >/dev/null

for attempt in $(seq 1 30); do
  probe_running="$(docker inspect --format '{{.State.Running}}' "${probe_name}")"
  if [[ "${probe_running}" = "false" ]]; then
    break
  fi
  if [[ "${attempt}" = 30 ]]; then
    docker logs "${probe_name}" >&2
    docker logs "${runtime_name}" >&2
    exit 1
  fi
  sleep 1
done

docker logs "${probe_name}"
probe_status="$(docker inspect --format '{{.State.ExitCode}}' "${probe_name}")"
if [[ "${probe_status}" != "0" ]]; then
  docker logs "${runtime_name}" >&2
  exit "${probe_status}"
fi
echo "AWS Lambda native Python streaming-runtime profile passed"
