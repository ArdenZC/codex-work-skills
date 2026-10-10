#!/usr/bin/env bash
# Owner-run Option B provisioning plan. This script is not run by candidate CI.
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage (Owner deployment host, as root):
  rq03f_operator_boundary.sh provision TRUST_ROOT CONTROLLER_ROOT PROFILE_SHA256 INDEX_SHA256

TRUST_ROOT must be the already materialized external TrustContext directory.
CONTROLLER_ROOT must be the reviewed, built controller copy outside the candidate checkout.
The controller copy must include Build Inventory 1.1 and must be launched through
scripts/operator_controller_bootstrap.py with Python -I -S -B and the Owner-pinned build SHA.
The script changes Unix account/file ownership and modes only; it never edits trust bytes.
EOF
  exit 2
}

[[ $# -eq 5 && $1 == provision ]] || usage
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "must run as root on the independent deployment host" >&2; exit 1; }

trust_root=$(realpath -e -- "$2")
controller_root=$(realpath -e -- "$3")
expected_profile_sha=$4
expected_index_sha=$5
[[ $expected_profile_sha =~ ^[a-f0-9]{64}$ && $expected_index_sha =~ ^[a-f0-9]{64}$ ]] || usage

repo_root=$(realpath -e -- "$(dirname -- "$0")/..")
case "$trust_root/" in "$repo_root/"*) echo "trust root must be outside the candidate checkout" >&2; exit 1;; esac
case "$controller_root/" in "$repo_root/"*) echo "controller root must be outside the candidate checkout" >&2; exit 1;; esac
[[ $trust_root != "$controller_root" && $trust_root/ != "$controller_root/"* && $controller_root/ != "$trust_root/"* ]] || {
  echo "trust and controller roots must be disjoint" >&2
  exit 1
}

profile="$trust_root/authority-profile.json"
index="$trust_root/operation-index.json"
[[ -f $profile && ! -L $profile && -f $index && ! -L $index ]] || {
  echo "trust root must contain ordinary authority-profile.json and operation-index.json" >&2
  exit 1
}
[[ $(sha256sum -- "$profile" | cut -d ' ' -f 1) == "$expected_profile_sha" ]] || {
  echo "authority profile SHA does not match Owner-supplied pin" >&2
  exit 1
}
[[ $(sha256sum -- "$index" | cut -d ' ' -f 1) == "$expected_index_sha" ]] || {
  echo "operation index SHA does not match Owner-supplied pin" >&2
  exit 1
}

for path in "$trust_root" "$controller_root"; do
  [[ ! -L $path ]] || { echo "symlink deployment root refused: $path" >&2; exit 1; }
  find "$path" -xdev \( -type l -o \( ! -type d -a ! -type f \) \) -print -quit | grep -q . && {
    echo "symlink or special file found under deployment root: $path" >&2
    exit 1
  }
done

# Bytecode caches are mutable derived state and are not part of the installed
# source closure. Python -B prevents the Operator process from recreating them.
find "$controller_root" -xdev -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$controller_root" -xdev -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

users=(rq03f-operator rq03f-candidate rq03f-author rq03f-reviewer-a rq03f-approver-b)
for user in "${users[@]}"; do
  if ! getent passwd "$user" >/dev/null; then
    useradd --system --create-home --home-dir "/var/lib/$user" --shell /usr/sbin/nologin "$user"
  fi
done

operator_uid=$(id -u rq03f-operator)
declare -A uid_owner=()
for user in "${users[@]}"; do
  user_uid=$(id -u "$user")
  [[ -z ${uid_owner[$user_uid]:-} ]] || { echo "role accounts must have distinct UIDs" >&2; exit 1; }
  uid_owner[$user_uid]=$user
done

python3 - "$profile" "$index" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    profile = json.load(stream)
with open(sys.argv[2], encoding="utf-8") as stream:
    index = json.load(stream)
if profile.get("profile_version") != "1.1":
    raise SystemExit("external profile must be the Owner-pinned Profile 1.1")
if index.get("index_version") != "1.1":
    raise SystemExit("external index must be the Owner-pinned Index 1.1")
if profile.get("policy_epoch") != index.get("policy_epoch"):
    raise SystemExit("external profile/index policy epochs differ")
principal = profile.get("qualification_corpus_custodian_principal")
roles = [row for row in profile.get("roles", []) if row.get("principal_id") == principal]
if len(roles) != 1 or roles[0].get("allowed_roles") != ["qualification_corpus_custodian"]:
    raise SystemExit("profile must grant only the dedicated corpus-custodian role")
PY

profile_operator_uid=$(python3 - "$profile" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["operator_unix_uid"])
PY
)
[[ $profile_operator_uid == "$operator_uid" ]] || {
  echo "Profile 1.1 Operator UID does not match rq03f-operator" >&2
  exit 1
}
profile_candidate_uids=$(python3 - "$profile" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    values = sorted(json.load(stream)["non_operator_process_unix_uids"])
print(",".join(str(value) for value in values))
PY
)
actual_candidate_uids=$(for user in rq03f-candidate rq03f-author rq03f-reviewer-a rq03f-approver-b; do id -u "$user"; done | sort -n | paste -sd, -)
[[ $profile_candidate_uids == "$actual_candidate_uids" ]] || {
  echo "Profile 1.1 non-Operator process UIDs do not match deployed Candidate/Author/Reviewer/Approver accounts" >&2
  exit 1
}

# The complete operator trust root is private to the dedicated custody identity.
chown -hR rq03f-operator:rq03f-operator -- "$trust_root"
find "$trust_root" -xdev -type d -exec chmod 0700 {} +
find "$trust_root" -xdev -type f -exec chmod 0600 {} +
# Controller source is immutable to every role account. The Owner-pinned
# controller build inventory is checked by the launch wrapper before execution.
chown -hR root:root -- "$controller_root"
find "$controller_root" -xdev -type d -exec chmod 0555 {} +
find "$controller_root" -xdev -type f -exec chmod 0444 {} +

[[ $(stat -c '%u' "$trust_root") == "$operator_uid" ]] || { echo "trust root owner mismatch" >&2; exit 1; }
[[ $(stat -c '%u' "$index") == "$operator_uid" ]] || { echo "operation index owner mismatch" >&2; exit 1; }
[[ $(stat -c '%a' "$trust_root") == 700 && $(stat -c '%a' "$index") == 600 ]] || {
  echo "trust root/index mode mismatch" >&2
  exit 1
}

for user in rq03f-candidate rq03f-author rq03f-reviewer-a rq03f-approver-b; do
  if runuser -u "$user" -- python3 -c 'import os,sys; fd=os.open(sys.argv[1], os.O_WRONLY|os.O_APPEND); os.close(fd)' "$index" >/dev/null 2>&1; then
    echo "$user unexpectedly opened the protected index for append" >&2
    exit 1
  fi
done
runuser -u rq03f-operator -- python3 -c 'import os,sys; fd=os.open(sys.argv[1], os.O_WRONLY|os.O_APPEND); os.close(fd)' "$index"

[[ $(sha256sum -- "$profile" | cut -d ' ' -f 1) == "$expected_profile_sha" ]] || {
  echo "authority profile bytes changed during permission provisioning" >&2
  exit 1
}
[[ $(sha256sum -- "$index" | cut -d ' ' -f 1) == "$expected_index_sha" ]] || {
  echo "operation index bytes changed during permission provisioning" >&2
  exit 1
}

printf 'operator_uid=%s\n' "$operator_uid"
for user in "${users[@]}"; do printf '%s_uid=%s\n' "$user" "$(id -u "$user")"; done
printf 'candidate_role_index_append=open_denied\nauthor_role_index_append=open_denied\nreviewer_role_index_append=open_denied\napprover_role_index_append=open_denied\noperator_index_append=open_allowed\n'
printf 'profile_sha256=%s\nindex_sha256=%s\n' "$expected_profile_sha" "$expected_index_sha"
