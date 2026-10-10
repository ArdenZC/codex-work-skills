#!/bin/bash
# Owner-run Linux Option B account and filesystem provisioning.
# This script is not a trust source and never edits protected JSON bytes.
set -euo pipefail
umask 077
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

readonly ROLE_USERS=(
  rq03f-operator
  rq03f-candidate
  rq03f-author
  rq03f-reviewer-a
  rq03f-approver-b
)
readonly NON_OPERATOR_USERS=(
  rq03f-candidate
  rq03f-author
  rq03f-reviewer-a
  rq03f-approver-b
)
CREATED_USERS=()

usage() {
  cat >&2 <<'EOF'
Usage (independent Linux deployment host, as root):
  rq03f_operator_boundary.sh create-accounts
  rq03f_operator_boundary.sh provision TRUST_ROOT CONTROLLER_ROOT RUNTIME_ROOT PROFILE_SHA256 INDEX_SHA256 BUILD_SHA256

Run create-accounts once on the clean deployment host first. It refuses to reuse
existing role names and prints the actual distinct UIDs. The external Owner then
pins those IDs into the synthetic/approved Profile 1.1 before running provision.

TRUST_ROOT must be the already materialized external TrustContext directory.
CONTROLLER_ROOT must be the reviewed installed controller copy outside the
candidate checkout. The controller must be launched with Python -I -S -B and
the external Owner-pinned build-inventory digest. This script changes Unix
accounts, ACLs, ownership, and modes only; it never edits trusted bytes.
EOF
  exit 2
}

fail() {
  printf 'operator boundary provisioning blocked: %s\n' "$1" >&2
  exit 1
}

require_root() {
  [[ $(id -u) -eq 0 ]] || fail 'must run as root on the independent Linux host'
}

cleanup_new_accounts() {
  local status=$?
  local cleanup_status=0
  if (( status != 0 )); then
    for user in "${CREATED_USERS[@]}"; do
      if getent passwd "$user" >/dev/null 2>&1; then
        userdel --remove -- "$user" >/dev/null 2>&1 \
          || { printf 'failed to roll back temporary role account: %s\n' "$user" >&2; cleanup_status=1; }
      fi
      if getent group "$user" >/dev/null 2>&1; then
        groupdel -- "$user" >/dev/null 2>&1 \
          || { printf 'failed to roll back temporary role group: %s\n' "$user" >&2; cleanup_status=1; }
      fi
    done
  fi
  if (( cleanup_status != 0 )); then status=1; fi
  exit "$status"
}

assert_role_account() {
  local user=$1
  local expected_home="/var/lib/$user"
  local entry name password uid gid gecos home shell
  local primary_gid groups home_owner home_mode passwd_state sudo_status
  entry=$(getent passwd "$user") || fail "role account is missing: $user"
  IFS=: read -r name password uid gid gecos home shell <<<"$entry"
  [[ $name == "$user" && $uid =~ ^[0-9]+$ && $gid =~ ^[0-9]+$ ]] \
    || fail "invalid passwd record for $user"
  (( uid > 0 )) || fail "role account must not use UID 0: $user"
  [[ $home == "$expected_home" && $shell == /usr/sbin/nologin ]] \
    || fail "role account home or non-login shell mismatch: $user"
  primary_gid=$gid
  [[ $(getent group "$user" | cut -d: -f3) == "$primary_gid" ]] \
    || fail "role account must have its own primary group: $user"
  groups=$(id -G -- "$user")
  [[ $groups == "$primary_gid" ]] \
    || fail "role account has supplementary group access: $user ($groups)"
  [[ $(id -Gn -- "$user") == "$user" ]] \
    || fail "role account has an unexpected group name: $user"
  home_owner=$(stat -c '%u' -- "$home")
  home_mode=$(stat -c '%a' -- "$home")
  [[ $home_owner == "$uid" && $home_mode == 700 ]] \
    || fail "role account home ownership/mode mismatch: $user"
  passwd_state=$(passwd -S "$user" | awk '{print $2}')
  [[ $passwd_state == L ]] || fail "role account password is not locked: $user"
  if setpriv --reuid="$uid" --regid="$gid" --clear-groups -- \
    /usr/bin/sudo -n true >/dev/null 2>&1; then
    sudo_status=0
    printf 'role_sudo_probe user=%s uid=%s exit_code=%s result=FAIL\n' "$user" "$uid" "$sudo_status" >&2
    fail "role account has sudo authorization: $user"
  else
    sudo_status=$?
  fi
  printf 'role_sudo_probe user=%s uid=%s exit_code=%s result=PASS\n' "$user" "$uid" "$sudo_status"
}

assert_all_role_accounts() {
  local user uid gid
  local -A uid_owner=()
  local -A gid_owner=()
  for user in "${ROLE_USERS[@]}"; do
    assert_role_account "$user"
    uid=$(id -u -- "$user")
    [[ -z ${uid_owner[$uid]:-} ]] || fail "role UIDs are not unique: $uid"
    uid_owner[$uid]=$user
    gid=$(id -g -- "$user")
    [[ -z ${gid_owner[$gid]:-} ]] || fail "role primary GIDs are not unique: $gid"
    gid_owner[$gid]=$user
  done
}

create_accounts() {
  require_root
  [[ -x /usr/bin/sudo ]] || fail 'the absolute /usr/bin/sudo path is required to verify direct role grants'
  command -v setpriv >/dev/null || fail 'setpriv is required to verify isolated role identities'
  trap cleanup_new_accounts EXIT
  local user
  for user in "${ROLE_USERS[@]}"; do
    getent passwd "$user" >/dev/null 2>&1 && fail "refusing to reuse pre-existing account: $user"
    getent group "$user" >/dev/null 2>&1 && fail "refusing to reuse pre-existing group: $user"
  done
  for user in "${ROLE_USERS[@]}"; do
    if ! useradd --system --user-group --no-log-init --create-home \
      --home-dir "/var/lib/$user" --shell /usr/sbin/nologin \
      --comment 'RQ03F temporary isolated role' -- "$user"; then
      CREATED_USERS+=("$user")
      fail "could not create fresh role account: $user"
    fi
    CREATED_USERS+=("$user")
    passwd --lock -- "$user" >/dev/null
    chmod 0700 -- "/var/lib/$user"
  done
  assert_all_role_accounts
  for user in "${ROLE_USERS[@]}"; do
    printf '%s_uid=%s\n' "$user" "$(id -u -- "$user")"
    printf '%s_gid=%s\n' "$user" "$(id -g -- "$user")"
  done
  trap - EXIT
}

canonical_existing_path() {
  local supplied=$1 canonical
  [[ $supplied == /* ]] || fail "deployment paths must be absolute: $supplied"
  canonical=$(realpath -e -- "$supplied") || fail "deployment path does not exist: $supplied"
  [[ $canonical == "$supplied" ]] || fail "deployment path must be canonical and alias-free: $supplied"
  [[ ! -L $canonical ]] || fail "symlink deployment root refused: $canonical"
  printf '%s\n' "$canonical"
}

assert_safe_ancestors() {
  local target=$1 allow_operator_parent=$2 cursor=/ component owner mode numeric_mode
  local operator_uid
  operator_uid=$(id -u -- rq03f-operator)
  IFS=/ read -r -a components <<<"${target#/}"
  for component in "${components[@]}"; do
    [[ -n $component ]] || continue
    cursor=${cursor%/}/$component
    [[ ! -L $cursor ]] || fail "symlink path component refused: $cursor"
    [[ -e $cursor ]] || fail "missing path component: $cursor"
    owner=$(stat -c '%u' -- "$cursor")
    mode=$(stat -c '%a' -- "$cursor")
    numeric_mode=$((8#$mode))
    if [[ $allow_operator_parent == true ]]; then
      [[ $owner == 0 || $owner == "$operator_uid" ]] \
        || fail "trust path component is not root/Operator-owned: $cursor"
    else
      [[ $owner == 0 ]] || fail "controller/runtime path component is not root-owned: $cursor"
    fi
    if (( (numeric_mode & 0022) != 0 && (numeric_mode & 01000) == 0 )); then
      fail "group/world-writable non-sticky deployment ancestor: $cursor"
    fi
  done
}

assert_clean_tree() {
  local root=$1 expected_owner_policy=$2
  python3 - "$root" "$expected_owner_policy" "$(id -u rq03f-operator)" \
    "$(id -u rq03f-candidate)" "$(id -u rq03f-author)" \
    "$(id -u rq03f-reviewer-a)" "$(id -u rq03f-approver-b)" <<'PY'
import os
import stat
import sys

root = os.path.abspath(sys.argv[1])
owner_policy = sys.argv[2]
operator_uid = int(sys.argv[3])
non_operator_uids = {int(value) for value in sys.argv[4:]}
root_stat = os.lstat(root)
if not stat.S_ISDIR(root_stat.st_mode):
    raise SystemExit(f"deployment root is not an ordinary directory: {root}")
if root_stat.st_mode & 0o022:
    raise SystemExit(f"group/world-writable deployment root refused: {root}")
if owner_policy == "root" and root_stat.st_uid != 0:
    raise SystemExit(f"deployment root must be root-owned: {root}")
if owner_policy == "trust" and root_stat.st_uid not in {0, operator_uid}:
    raise SystemExit(f"trust root has an untrusted owner: {root}")
if root_stat.st_uid in non_operator_uids:
    raise SystemExit(f"non-Operator role owns deployment root: {root}")
root_device = root_stat.st_dev
for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
    for name in dirs + files:
        path = os.path.join(current, name)
        info = os.lstat(path)
        if info.st_dev != root_device:
            raise SystemExit(f"nested mount/device boundary refused: {path}")
        if stat.S_ISLNK(info.st_mode):
            raise SystemExit(f"symlink refused in deployment tree: {path}")
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise SystemExit(f"special file refused in deployment tree: {path}")
        if info.st_mode & 0o022:
            raise SystemExit(f"group/world-writable deployment object refused: {path}")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise SystemExit(f"hard-linked deployment file refused: {path}")
        if info.st_uid in non_operator_uids:
            raise SystemExit(f"non-Operator role owns deployment content: {path}")
        if owner_policy == "root" and info.st_uid != 0:
            raise SystemExit(f"controller tree must be root-owned: {path}")
        if owner_policy == "trust" and info.st_uid not in {0, operator_uid}:
            raise SystemExit(f"trust tree has an untrusted owner: {path}")
PY
}

assert_no_named_acls() {
  local path=$1 acl_output
  acl_output=$(getfacl --recursive --omit-header --absolute-names -- "$path") \
    || fail "cannot inspect ACLs for $path"
  if grep -Eq '^(default:)?(user|group):[^:]' <<<"$acl_output"; then
    fail "named/default ACL entries remain in deployment tree: $path"
  fi
}

provision() {
  require_root
  [[ -x /usr/bin/sudo ]] || fail 'the absolute /usr/bin/sudo path is required to verify direct role grants'
  command -v setpriv >/dev/null || fail 'setpriv is required to verify isolated role identities'
  command -v getfacl >/dev/null && command -v setfacl >/dev/null \
    || fail 'acl package (getfacl/setfacl) is required for effective permission checks'
  [[ $# -eq 6 ]] || usage
  assert_all_role_accounts
  local trust_root controller_root runtime_root expected_profile_sha expected_index_sha expected_build_sha
  trust_root=$(canonical_existing_path "$1")
  controller_root=$(canonical_existing_path "$2")
  runtime_root=$(canonical_existing_path "$3")
  expected_profile_sha=$4
  expected_index_sha=$5
  expected_build_sha=$6
  [[ $expected_profile_sha =~ ^[a-f0-9]{64}$ && $expected_index_sha =~ ^[a-f0-9]{64}$ \
    && $expected_build_sha =~ ^[a-f0-9]{64}$ ]] || usage

  local repo_root
  repo_root=$(realpath -e -- "$(dirname -- "$0")/..")
  case "$trust_root/" in "$repo_root/"*) fail 'trust root must be outside the candidate checkout';; esac
  case "$controller_root/" in "$repo_root/"*) fail 'controller root must be outside the candidate checkout';; esac
  case "$runtime_root/" in "$repo_root/"*) fail 'runtime root must be outside the candidate checkout';; esac
  local first second
  for first in "$trust_root" "$controller_root" "$runtime_root"; do
    for second in "$trust_root" "$controller_root" "$runtime_root"; do
      [[ $first == "$second" ]] && continue
      [[ $first/ != "$second/"* && $second/ != "$first/"* ]] \
        || fail 'trust, controller, and runtime roots must be disjoint'
    done
  done
  assert_safe_ancestors "$trust_root" true
  assert_safe_ancestors "$controller_root" false
  assert_safe_ancestors "$runtime_root" false
  assert_clean_tree "$trust_root" trust
  assert_clean_tree "$controller_root" root
  assert_clean_tree "$runtime_root" root

  local profile="$trust_root/authority-profile.json" index="$trust_root/operation-index.json"
  [[ -f $profile && ! -L $profile && -f $index && ! -L $index ]] \
    || fail 'trust root must contain ordinary authority-profile.json and operation-index.json'
  [[ $(sha256sum -- "$profile" | cut -d ' ' -f 1) == "$expected_profile_sha" ]] \
    || fail 'authority profile SHA does not match Owner-supplied pin'
  [[ $(sha256sum -- "$index" | cut -d ' ' -f 1) == "$expected_index_sha" ]] \
    || fail 'operation index SHA does not match Owner-supplied pin'

  python3 - "$profile" "$index" "$trust_root" "$controller_root" "$runtime_root" \
    "$expected_build_sha" "$(id -u rq03f-operator)" \
    "$(id -u rq03f-candidate)" "$(id -u rq03f-author)" \
    "$(id -u rq03f-reviewer-a)" "$(id -u rq03f-approver-b)" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    profile = json.load(stream)
with open(sys.argv[2], encoding="utf-8") as stream:
    index = json.load(stream)
trust_root = Path(sys.argv[3])
controller_root = Path(sys.argv[4])
runtime_root = Path(sys.argv[5])
expected_build_sha = sys.argv[6]
expected_operator_uid = int(sys.argv[7])
expected_non_operator_uids = sorted(int(value) for value in sys.argv[8:])
if profile.get("profile_version") != "1.1":
    raise SystemExit("external profile must be the Owner-pinned Profile 1.1")
if index.get("index_version") != "1.1":
    raise SystemExit("external index must be the Owner-pinned Index 1.1")
if profile.get("operator_unix_uid") != expected_operator_uid:
    raise SystemExit("Profile 1.1 Operator UID does not match the newly provisioned role account")
if sorted(profile.get("non_operator_process_unix_uids", [])) != expected_non_operator_uids:
    raise SystemExit("Profile 1.1 process UIDs do not match the newly provisioned role accounts")
if profile.get("policy_epoch") != index.get("policy_epoch"):
    raise SystemExit("external profile/index policy epochs differ")
principal = profile.get("qualification_corpus_custodian_principal")
roles = [row for row in profile.get("roles", []) if row.get("principal_id") == principal]
if len(roles) != 1 or roles[0].get("allowed_roles") != ["qualification_corpus_custodian"]:
    raise SystemExit("profile must grant only the dedicated corpus-custodian role")
if profile.get("controller_build_inventory_sha256") is None:
    raise SystemExit("Profile 1.1 must pin an installed Controller Build Inventory")
if profile["controller_build_inventory_sha256"] != expected_build_sha:
    raise SystemExit("Profile build inventory SHA does not match the Owner-supplied pin")
build_key = profile.get("controller_build_inventory_key")
if not isinstance(build_key, str) or not build_key:
    raise SystemExit("Profile 1.1 has no controller build inventory key")
build_path = trust_root / (build_key.replace(":", "_") + ".bin")
build_raw = build_path.read_bytes()
if hashlib.sha256(build_raw).hexdigest() != expected_build_sha:
    raise SystemExit("Controller Build Inventory does not match the Owner-supplied SHA")
build = json.loads(build_raw)
if build.get("build_inventory_version") != "1.1":
    raise SystemExit("Owner-pinned Controller Build Inventory must be version 1.1")
if Path(build["controller_root"]).resolve(strict=True) != controller_root.resolve(strict=True):
    raise SystemExit("Build Inventory controller root differs from the protected installation")
runtime = build["python_runtime"]
if not Path(runtime["site_packages_root"]).resolve(strict=True).is_relative_to(runtime_root.resolve(strict=True)):
    raise SystemExit("Build Inventory site-packages root is outside the protected runtime root")
if not Path(runtime["python_executable"]).resolve(strict=True).is_relative_to(runtime_root.resolve(strict=True)):
    raise SystemExit("Build Inventory Python executable is outside the protected runtime root")
PY

  # Reject named and default ACLs before applying the final private modes.
  setfacl --recursive --remove-all -- "$trust_root" "$controller_root" "$runtime_root"
  assert_no_named_acls "$trust_root"
  assert_no_named_acls "$controller_root"
  assert_no_named_acls "$runtime_root"

  # Bytecode caches are mutable derived state and are not part of the installed
  # source closure. Python -B prevents the Operator process from recreating them.
  find "$controller_root" -type d -name __pycache__ -prune -exec rm -rf -- {} +
  find "$controller_root" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

  chown -R rq03f-operator:rq03f-operator -- "$trust_root"
  find "$trust_root" -type d -exec chmod 0700 -- {} +
  find "$trust_root" -type f -exec chmod 0600 -- {} +
  chown -R root:root -- "$controller_root"
  find "$controller_root" -type d -exec chmod 0555 -- {} +
  find "$controller_root" -type f -exec chmod 0444 -- {} +
  chown -R root:root -- "$runtime_root"
  find "$runtime_root" -type d -exec chmod 0555 -- {} +
  find "$runtime_root" -type f -perm /111 -exec chmod 0555 -- {} +
  find "$runtime_root" -type f ! -perm /111 -exec chmod 0444 -- {} +

  [[ $(stat -c '%u' -- "$trust_root") == "$(id -u rq03f-operator)" ]] || fail 'trust root owner mismatch'
  [[ $(stat -c '%u' -- "$index") == "$(id -u rq03f-operator)" ]] || fail 'operation index owner mismatch'
  [[ $(stat -c '%a' -- "$trust_root") == 700 && $(stat -c '%a' -- "$index") == 600 ]] \
    || fail 'trust root/index mode mismatch'
  [[ $(stat -c '%u' -- "$controller_root") == 0 && $(stat -c '%a' -- "$controller_root") == 555 ]] \
    || fail 'installed controller root must be root-owned and read/execute-only'
  [[ $(stat -c '%u' -- "$runtime_root") == 0 && $(stat -c '%a' -- "$runtime_root") == 555 ]] \
    || fail 'installed Python runtime root must be root-owned and read/execute-only'
  assert_no_named_acls "$trust_root"
  assert_no_named_acls "$controller_root"
  assert_no_named_acls "$runtime_root"

  local user uid
  for user in "${NON_OPERATOR_USERS[@]}"; do
    uid=$(id -u -- "$user")
    if setpriv --reuid="$uid" --regid="$(id -g -- "$user")" --clear-groups \
      --no-new-privs --bounding-set=-all --inh-caps=-all --ambient-caps=-all -- \
      python3 -c 'import os,sys; fd=os.open(sys.argv[1], os.O_WRONLY|os.O_APPEND); os.close(fd)' "$index" \
      >/dev/null 2>&1; then
      fail "$user unexpectedly opened the protected index for append"
    fi
  done
  setpriv --reuid="$(id -u rq03f-operator)" --regid="$(id -g rq03f-operator)" \
    --clear-groups --no-new-privs --bounding-set=-all --inh-caps=-all --ambient-caps=-all -- \
    python3 -c 'import os,sys; fd=os.open(sys.argv[1], os.O_WRONLY|os.O_APPEND); os.close(fd)' "$index"

  [[ $(sha256sum -- "$profile" | cut -d ' ' -f 1) == "$expected_profile_sha" ]] \
    || fail 'authority profile bytes changed during permission provisioning'
  [[ $(sha256sum -- "$index" | cut -d ' ' -f 1) == "$expected_index_sha" ]] \
    || fail 'operation index bytes changed during permission provisioning'

  printf 'trust_root=%s\ncontroller_root=%s\n' "$trust_root" "$controller_root"
  for user in "${ROLE_USERS[@]}"; do
    printf '%s_uid=%s\n%s_gid=%s\n' "$user" "$(id -u -- "$user")" "$user" "$(id -g -- "$user")"
  done
  printf 'candidate_role_index_append=open_denied\nauthor_role_index_append=open_denied\nreviewer_role_index_append=open_denied\napprover_role_index_append=open_denied\noperator_index_append=open_allowed\n'
  printf 'profile_sha256=%s\nindex_sha256=%s\n' "$expected_profile_sha" "$expected_index_sha"
}

[[ $# -ge 1 ]] || usage
case "$1" in
  create-accounts)
    [[ $# -eq 1 ]] || usage
    create_accounts
    ;;
  provision)
    shift
    provision "$@"
    ;;
  *)
    usage
    ;;
esac
