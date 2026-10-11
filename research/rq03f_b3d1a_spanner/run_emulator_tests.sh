#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
python_exec="${RQ03F_SPANNER_PYTHON:-python3}"
emulator_image="gcr.io/cloud-spanner-emulator/emulator@sha256:c6f3402f2599684f295a0fdefb6fbbbfb18a0e43e309ff5456ccb452a4570a79"
container_name="rq03f-b3d1a-spanner-emulator-${BASHPID}"

docker pull "$emulator_image"
docker run --rm --detach --name "$container_name" \
  -p 127.0.0.1:9010:9010 -p 127.0.0.1:9020:9020 \
  "$emulator_image" >/dev/null

cleanup() {
  docker stop "$container_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

ready=0
for attempt in $(seq 1 30); do
  if docker logs "$container_name" 2>&1 | grep -qF "Cloud Spanner Emulator running."; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  docker logs "$container_name" >&2
  exit 1
fi

PYTHONPATH="$repo_root/research/rq03f_b3d1a_spanner" \
SPANNER_EMULATOR_HOST=127.0.0.1:9010 \
"$python_exec" -m unittest discover \
  -s research/rq03f_b3d1a_spanner/tests -p 'test_*.py' -v
