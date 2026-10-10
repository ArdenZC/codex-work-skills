#!/usr/bin/env bash
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
run_tag="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
test_root="/var/lib/rq03f-c1-${run_tag}"
evidence_dir="${RUNNER_TEMP:-/tmp}/rq03f-c1-evidence"
evidence_file="$evidence_dir/hosted-isolation.txt"
python_bin=$(command -v python)
roles=(operator candidate author reviewer approver)
role_users=()
created_users=()

mkdir -p "$evidence_dir"
chmod 0700 "$evidence_dir"
: > "$evidence_file"

log() {
  printf '%s\n' "$*" | tee -a "$evidence_file"
}

cleanup() {
  set +e
  for user in "${created_users[@]}"; do
    sudo -n userdel "$user" >/dev/null 2>&1
    sudo -n groupdel "$user" >/dev/null 2>&1
  done
  sudo -n rm -rf -- "$test_root"
}
trap cleanup EXIT

for role in "${roles[@]}"; do
  user="rq03f-c1-${role}"
  if getent passwd "$user" >/dev/null || getent group "$user" >/dev/null; then
    log "FAIL identity collision: $user already exists"
    exit 2
  fi
  role_users+=("$user")
done
if sudo -n test -e "$test_root"; then
  log "FAIL test path already exists: $test_root"
  exit 2
fi

for index in "${!roles[@]}"; do
  user=${role_users[$index]}
  uid=$((4601 + index))
  if getent passwd "$uid" >/dev/null || getent group "$uid" >/dev/null; then
    log "FAIL numeric identity collision: $uid"
    exit 2
  fi
  sudo -n useradd --uid "$uid" --user-group --no-create-home --shell /usr/sbin/nologin "$user"
  created_users+=("$user")
done

operator=${role_users[0]}
candidate=${role_users[1]}
author=${role_users[2]}
reviewer=${role_users[3]}
approver=${role_users[4]}
operator_uid=$(id -u "$operator")
operator_gid=$(id -g "$operator")
candidate_uid=$(id -u "$candidate")

sudo -n install -d -o root -g root -m 0755 "$test_root"
sudo -n install -d -o root -g root -m 0755 "$test_root/formal-trust-placeholder"
sudo -n install -d -o "$operator" -g "$operator" -m 0700 \
  "$test_root/operator-work" "$test_root/operator-generation-parent" \
  "$test_root/operator-acl-parent" "$test_root/protected-evidence"

run_as() {
  local user=$1
  shift
  local uid gid
  uid=$(id -u "$user")
  gid=$(id -g "$user")
  sudo -n /usr/bin/setpriv --reuid="$uid" --regid="$gid" --clear-groups \
    --inh-caps=-all --ambient-caps=-all --bounding-set=-all -- \
    /usr/bin/env -i HOME="$test_root/operator-work" PATH=/usr/bin:/bin LC_ALL=C PYTHONUTF8=1 "$@"
}

for user in "${role_users[@]}"; do
  uid=$(id -u "$user")
  gid=$(id -g "$user")
  actual_uid=$(run_as "$user" /usr/bin/id -u)
  groups=$(run_as "$user" /usr/bin/id -G)
  cap_eff=$(run_as "$user" /usr/bin/awk '/^CapEff:/{print $2}' /proc/self/status)
  [[ "$actual_uid" == "$uid" && "$groups" == "$gid" && "$cap_eff" == "0000000000000000" ]]
  log "IDENTITY role=$user uid=$actual_uid gid=$gid supplementary_groups=none effective_caps=$cap_eff"
done

run_as "$operator" "$python_bin" -c \
  'from pathlib import Path; p=Path(__import__("sys").argv[1]); (p/"authority-profile.json").write_bytes(b"synthetic-profile\n"); (p/"operation-index.json").write_bytes(b"synthetic-index\n"); [(q.chmod(0o600)) for q in p.iterdir()]' \
  "$test_root/protected-evidence"
operator_read_hashes=$(run_as "$operator" "$python_bin" -c \
  'import hashlib,pathlib,sys; root=pathlib.Path(sys.argv[1]); print(";".join(f"{p.name}:{hashlib.sha256(p.read_bytes()).hexdigest()}" for p in sorted(root.glob("*.json"))))' \
  "$test_root/protected-evidence")
[[ "$operator_read_hashes" == *"authority-profile.json:"* && "$operator_read_hashes" == *"operation-index.json:"* ]]
log "OPERATOR_READ uid=$operator_uid result=$operator_read_hashes"

probe_python='import errno,os,sys
root,index=sys.argv[1:]
ops={
 "profile_read":lambda: open(os.path.join(root,"authority-profile.json"),"rb").read(),
 "index_read":lambda: open(index,"rb").read(),
 "index_write":lambda: open(index,"ab").write(b"forged"),
 "index_unlink":lambda: os.unlink(index),
 "index_rename":lambda: os.rename(index,index+".candidate"),
 "index_create":lambda: open(os.path.join(root,"forged.json"),"xb").write(b"forged"),
}
failed=[]
for name,action in ops.items():
 try: action()
 except OSError as exc:
  if exc.errno not in (errno.EACCES,errno.EPERM): failed.append((name,exc.errno))
  else: print(f"{name}=DENIED errno={exc.errno}")
 else: failed.append((name,"unexpected-success")); print(f"{name}=UNEXPECTED_SUCCESS")
if failed: print(f"unexpected={failed}"); raise SystemExit(1)'

for user in "$candidate" "$author" "$reviewer" "$approver"; do
  actual_uid=$(run_as "$user" /usr/bin/id -u)
  set +e
  run_as "$user" "$python_bin" -c "$probe_python" \
    "$test_root/protected-evidence" "$test_root/protected-evidence/operation-index.json" \
    >"$evidence_dir/${user}.probe.txt" 2>&1
  probe_status=$?
  set -e
  probe_output=$(cat "$evidence_dir/${user}.probe.txt")
  if [[ $probe_status -ne 0 ]]; then
    log "ROLE_DENY role=$user uid=$actual_uid result=FAIL probe_exit_code=$probe_status"
    printf '%s\n' "$probe_output" | tee -a "$evidence_file"
    exit 1
  fi
  for operation in profile_read index_read index_write index_unlink index_rename index_create; do
    if ! grep -Eq "^${operation}=DENIED errno=(1|13)$" "$evidence_dir/${user}.probe.txt"; then
      log "ROLE_DENY role=$user uid=$actual_uid result=FAIL missing_denial=$operation"
      printf '%s\n' "$probe_output" | tee -a "$evidence_file"
      exit 1
    fi
  done
  log "ROLE_DENY role=$user uid=$actual_uid result=PASS exit_code=$probe_status"
  sed 's/^/  /' "$evidence_dir/${user}.probe.txt" | tee -a "$evidence_file"
done

sudo -n setfacl -m "u:${reviewer_uid:-$(id -u "$reviewer")}:r-x" "$test_root/operator-acl-parent"
setfacl_text=$(sudo -n getfacl -cp "$test_root/operator-acl-parent")
log "ACL_TEST reviewer_uid=$(id -u "$reviewer") parent=$test_root/operator-acl-parent"
printf '%s\n' "$setfacl_text" | tee -a "$evidence_file"

plan_dir="$test_root/owner-pinned-attempt"
log "OWNER_PLAN_SETUP stage=create-directory path=$plan_dir"
sudo -n install -d -o root -g root -m 0755 "$plan_dir"
operator_code_dir="$test_root/operator-code"
sudo -n install -d -o root -g root -m 0755 "$operator_code_dir"
allocator_source="$repo_root/tools/rq03f_c1/operator_allocator.py"
allocator_copy="$operator_code_dir/operator_allocator.py"
allocator_source_sha=$(sha256sum "$allocator_source" | cut -d ' ' -f1)
sudo -n install -o root -g root -m 0444 "$allocator_source" "$allocator_copy"
allocator_copy_sha=$(sha256sum "$allocator_copy" | cut -d ' ' -f1)
[[ "$allocator_copy_sha" == "$allocator_source_sha" ]]
log "CANDIDATE_TOOL_INPUT source_sha256=$allocator_source_sha read_only_copy_sha256=$allocator_copy_sha copy_owner=$(stat -c %u "$allocator_copy") copy_mode=$(stat -c %a "$allocator_copy")"
source_commit=$(git -C "$repo_root" rev-parse HEAD)
parent="$test_root/operator-generation-parent"
parent_device=$(stat -c %d "$parent")
parent_inode=$(stat -c %i "$parent")
parent_mount_id=$(findmnt -n -o ID -T "$parent")
log "OWNER_PLAN_SETUP stage=parent-pinned device=$parent_device inode=$parent_inode mount_id=$parent_mount_id operator_uid=$operator_uid operator_gid=$operator_gid source_commit=$source_commit"
plan_path="$plan_dir/plan.json"
sudo -n /usr/bin/python3 - "$plan_path" "$parent" "$parent_device" "$parent_inode" \
  "$parent_mount_id" "$operator_uid" "$operator_gid" "$source_commit" "$repo_root" <<'PY'
import json,os,sys
path,parent,device,inode,mount_id,uid,gid,commit,checkout=sys.argv[1:]
payload={
 "schema_version":"rq03f-exclusive-allocation-plan-1.0",
 "operation_kind":"generation",
 "operation_scope":"qualification_controller_generation",
 "target_id":"rq03f-c1-unauthorized-candidate-attempt",
 "trusted_parent":parent,
 "protected_trust_root":os.path.join(os.path.dirname(parent),"formal-trust-placeholder"),
 "parent_device":int(device),
 "parent_inode":int(inode),
 "parent_mount_id":int(mount_id),
 "operator_uid":int(uid),
 "operator_gid":int(gid),
 "source_commit":commit,
 "source_checkout":checkout,
 "archive_sources":None,
}
raw=(json.dumps(payload,sort_keys=True,separators=(",",":"))+"\n").encode()
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o444)
try: os.write(fd,raw); os.fsync(fd)
finally: os.close(fd)
PY
plan_sha=$(sha256sum "$plan_path" | cut -d ' ' -f1)
log "OWNER_PLAN_SETUP stage=plan-created path=$plan_path sha256=$plan_sha"
set +e
candidate_attempt=$(run_as "$candidate" "$python_bin" "$allocator_copy" allocate \
  --plan "$plan_path" --expected-plan-sha256 "$plan_sha" 2>&1)
candidate_status=$?
set -e
log "CANDIDATE_PLAN_SUBSTITUTION stage=identity-check uid=$candidate_uid expected_operator_uid=$operator_uid exit_code=$candidate_status"
printf '%s\n' "$candidate_attempt" | tee -a "$evidence_file"
[[ $candidate_status -ne 0 ]]
[[ "$candidate_attempt" == *"exact non-root Owner-approved Operator UID"* ]]
log "CANDIDATE_PLAN_SUBSTITUTION result=DENIED"
[[ ! -e "$parent/rq03f-c1-unauthorized-candidate-attempt" ]]

export RQ03F_C1_TEST_TMPDIR="$test_root/operator-work"
export RQ03F_C1_ACL_TEST_PARENT="$test_root/operator-acl-parent"
set +e
run_as "$operator" /usr/bin/env RQ03F_C1_TEST_TMPDIR="$test_root/operator-work" \
  RQ03F_C1_ACL_TEST_PARENT="$test_root/operator-acl-parent" \
  "$python_bin" -m unittest \
  tests.test_rq03f_c1_operator_infrastructure -v 2>&1 | tee "$evidence_dir/unittest.txt" | tee -a "$evidence_file"
test_status=${PIPESTATUS[0]}
set -e
[[ $test_status -eq 0 ]]
log "NONROOT_OPERATOR_SUITE uid=$operator_uid result=PASS exit_code=$test_status"

[[ ! -e "$parent/rq03f-c1-unauthorized-candidate-attempt" ]]
log "POSTCONDITION protected_parent_generation_absent=true"
log "HOSTED_SCOPE synthetic_only=true formal_trust_established=false"
