"""GitHub-hosted, disposable Linux UID/filesystem boundary qualification.

This harness writes only under dedicated synthetic paths on the ephemeral
runner. It never reads or writes the formal Owner Trust Anchor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import time
import traceback
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
BOUNDARY_SCRIPT = REPO_ROOT / "tools/rq03f_operator_boundary.sh"
SOURCE_SCRIPTS = REPO_ROOT / "教案生成器/lesson-plan-docx-generator/scripts"
SOURCE_SCHEMAS = REPO_ROOT / "教案生成器/lesson-plan-docx-generator/schemas"
REQUIREMENTS = REPO_ROOT / "教案生成器/lesson-plan-docx-generator/requirements.txt"

STAGE_ROOT = Path("/var/lib/rq03f-b3-install")
CONTROLLER_ROOT = STAGE_ROOT / "controller"
RUNTIME_ROOT = STAGE_ROOT / "runtime"
TRUST_DATA_ROOT = Path("/var/lib/rq03f-operator/rq03f-b3-data")
TRUST_ROOT = TRUST_DATA_ROOT / "operator" / "trust"
RUN_ROOT = TRUST_DATA_ROOT / "candidate"
LAUNCHER = Path("/usr/local/sbin/rq03f-b3-operator-launch")
MARKER = Path("/tmp/rq03f-b3-shadow-imported")

ROLE_USERS = (
    "rq03f-operator",
    "rq03f-candidate",
    "rq03f-author",
    "rq03f-reviewer-a",
    "rq03f-approver-b",
)
NON_OPERATOR_USERS = ROLE_USERS[1:]

FAILURES: list[str] = []
CREATED_ACCOUNTS: list[str] = []
STAGE_CREATED = False
TRUST_DATA_CREATED = False
LAUNCHER_CREATED = False
REUSE_FIXTURE_CREATED = False
MARKER_CREATED = False


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _root_sha256(path: Path) -> str:
    result = _root_command(["sha256sum", "--", str(path)], label=f"read pinned test digest:{path.name}")
    if result.returncode != 0:
        raise RuntimeError(f"cannot read root-protected synthetic file digest: {path}")
    return result.stdout.split()[0]


def _root_command(command: list[str], *, label: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [
            "sudo",
            "-n",
            "env",
            "-i",
            "HOME=/root",
            "PATH=/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG=C.UTF-8",
            "LC_ALL=C.UTF-8",
            "PYTHONUTF8=1",
            "/bin/bash",
            "-c",
            "umask 077; exec \"$@\"",
            "rq03f-root-command",
            *command,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        close_fds=True,
        check=False,
    )
    _report_result(label, "runner-root-provisioner", 0, command, result, expected)
    return result


def _report_result(
    label: str,
    user: str,
    uid: int,
    command: list[str],
    result: subprocess.CompletedProcess[str],
    expected: int | str,
    *,
    env_keys: tuple[str, ...] = (),
) -> None:
    if expected == "nonzero":
        passed = result.returncode != 0
    else:
        passed = result.returncode == expected
    if not passed:
        FAILURES.append(f"{label}: exit {result.returncode}, expected {expected}")
    row = {
        "label": label,
        "user": user,
        "uid": uid,
        "command": command,
        "environment_overrides": list(env_keys),
        "exit_code": result.returncode,
        "expected": expected,
        "result": "PASS" if passed else "FAIL",
        "stdout": result.stdout.strip()[-3000:],
        "stderr": result.stderr.strip()[-1500:],
    }
    print("B3_TEST=" + json.dumps(row, ensure_ascii=False, sort_keys=True), flush=True)


def _identity(user: str) -> tuple[int, int]:
    record = pwd.getpwnam(user)
    return record.pw_uid, record.pw_gid


def _setpriv_command(
    user: str,
    command: list[str],
    *,
    extra_env: dict[str, str] | None = None,
) -> tuple[list[str], tuple[str, ...]]:
    uid, gid = _identity(user)
    env = [
        "/usr/bin/env",
        "-i",
        f"HOME={pwd.getpwnam(user).pw_dir}",
        f"USER={user}",
        f"LOGNAME={user}",
        "PATH=/usr/bin:/bin",
    ]
    env_keys: tuple[str, ...] = ()
    if extra_env:
        env.extend(f"{key}={value}" for key, value in sorted(extra_env.items()))
        env_keys = tuple(sorted(extra_env))
    return (
        [
            "sudo",
            "-n",
            "setpriv",
            f"--reuid={uid}",
            f"--regid={gid}",
            "--clear-groups",
            "--no-new-privs",
            "--bounding-set=-all",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            "--",
            *env,
            *command,
        ],
        env_keys,
    )


def _run_as(
    user: str,
    label: str,
    command: list[str],
    expected: int | str,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    uid, _gid = _identity(user)
    full_command, env_keys = _setpriv_command(user, command, extra_env=extra_env)
    result = subprocess.run(
        full_command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        close_fds=True,
        check=False,
    )
    _report_result(label, user, uid, command, result, expected, env_keys=env_keys)
    return result


def _run_direct_sudo_probe(user: str) -> None:
    """Check sudo policy as the real role UID without no_new_privs masking it."""
    uid, gid = _identity(user)
    home = pwd.getpwnam(user).pw_dir
    identity_probe = (
        "import os; "
        "print('sudo_probe_identity=' + str({'uid':os.getuid(),'euid':os.geteuid(),'gid':os.getgid(),'groups':os.getgroups()}),flush=True); "
        "os.execv('/usr/bin/sudo',['/usr/bin/sudo','-n','true'])"
    )
    command = [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/setpriv",
        f"--reuid={uid}",
        f"--regid={gid}",
        "--clear-groups",
        "--",
        "/usr/bin/env",
        "-i",
        f"HOME={home}",
        f"USER={user}",
        f"LOGNAME={user}",
        "PATH=/usr/bin:/bin",
        "/usr/bin/python3",
        "-I",
        "-S",
        "-c",
        identity_probe,
    ]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        close_fds=True,
        check=False,
    )
    _report_result(
        f"direct sudo grant probe as actual UID:{user}",
        user,
        uid,
        ["/usr/bin/sudo", "-n", "true"],
        result,
        "nonzero",
    )
    if (
        f"'uid': {uid}" not in result.stdout
        or f"'euid': {uid}" not in result.stdout
        or f"'gid': {gid}" not in result.stdout
        or "'groups': []" not in result.stdout
    ):
        FAILURES.append(f"direct sudo probe did not report the expected real UID for {user}")


def _stage_roots() -> None:
    for path in (STAGE_ROOT, TRUST_DATA_ROOT):
        check = _root_command(["test", "!", "-e", str(path)], label=f"fresh-path:{path}")
        if check.returncode != 0:
            raise RuntimeError(f"refusing to overwrite pre-existing hosted test path: {path}")

    _root_command(
        ["install", "-d", "-o", "root", "-g", "root", "-m", "0755", str(STAGE_ROOT)],
        label="create isolated stage root",
    )
    global STAGE_CREATED
    STAGE_CREATED = True
    _root_command(
        ["install", "-d", "-o", "root", "-g", "root", "-m", "0755", str(CONTROLLER_ROOT)],
        label="create isolated controller install root",
    )
    _root_command(
        ["cp", "-a", "--no-preserve=ownership", str(SOURCE_SCRIPTS), str(CONTROLLER_ROOT / "scripts")],
        label="copy controller scripts into external test install",
    )
    _root_command(
        ["cp", "-a", "--no-preserve=ownership", str(SOURCE_SCHEMAS), str(CONTROLLER_ROOT / "schemas")],
        label="copy controller schemas into external test install",
    )
    _root_command(
        [
            "cp",
            str(REPO_ROOT / "tools/rq03f_b3_hosted_operator_probe.py"),
            str(CONTROLLER_ROOT / "scripts/rq03f_b3_hosted_operator_probe.py"),
        ],
        label="install B3-only bootstrap entrypoint into external test install",
    )
    _root_command(
        [sys.executable, "-m", "venv", "--copies", str(RUNTIME_ROOT)],
        label="create separate copied Python runtime",
    )
    _root_command(
        [
            "python3",
            "-c",
            "import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
            "(p.is_symlink() and p.readlink()==pathlib.Path('lib') and p.unlink()) "
            "or (not p.exists() and not p.is_symlink()) or sys.exit('unexpected venv lib64 alias')",
            str(RUNTIME_ROOT / "lib64"),
        ],
        label="remove unused venv lib64 alias before pinning the runtime",
    )
    _root_command(
        [
            str(RUNTIME_ROOT / "bin/python"),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(REQUIREMENTS),
        ],
        label="install controller requirements in protected test runtime",
    )
    _root_command(
        [
            "find",
            str(RUNTIME_ROOT),
            "-xdev",
            "-type",
            "d",
            "-exec",
            "chmod",
            "go-w",
            "--",
            "{}",
            "+",
        ],
        label="remove group/other write bits from temporary runtime directories",
    )
    _root_command(
        [
            "find",
            str(RUNTIME_ROOT),
            "-xdev",
            "-type",
            "f",
            "-exec",
            "chmod",
            "go-w",
            "--",
            "{}",
            "+",
        ],
        label="remove group/other write bits from temporary runtime files",
    )


def _prepare_fixture() -> dict:
    if os.geteuid() != 0:
        raise RuntimeError("--prepare must run in the privileged disposable-runner phase")
    TRUST_DATA_ROOT.mkdir(mode=0o755)
    TRUST_DATA_ROOT.chmod(0o755)
    data_root_stat = TRUST_DATA_ROOT.stat()
    if data_root_stat.st_uid != 0 or data_root_stat.st_mode & 0o777 != 0o755:
        raise RuntimeError("synthetic TrustContext data root must be root-owned and mode 0755")
    controller_scripts = CONTROLLER_ROOT / "scripts"
    controller_schemas = CONTROLLER_ROOT / "schemas"
    operator_uid, _ = _identity("rq03f-operator")
    non_operator_uids = sorted(_identity(user)[0] for user in NON_OPERATOR_USERS)

    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(controller_scripts))
    import tests.test_qualification_corpus_intake as intake_tests
    from lifecycle_digest import canonical_json_bytes, sha256_bytes

    intake_tests.SCRIPTS = controller_scripts
    intake_tests.SCHEMAS = controller_schemas
    intake_tests.STATIC_TRUST_ROOT = TRUST_ROOT
    intake_tests._site_packages_digest.cache_clear()
    intake_tests._component_tree_digest.cache_clear()
    intake_tests._static_source_bytes.cache_clear()
    intake_tests._seed_static_trust_file.cache_clear()

    fixture = intake_tests.IntakeFixture(TRUST_DATA_ROOT)
    if fixture.trust_root != TRUST_ROOT:
        raise RuntimeError(f"synthetic fixture trust root mismatch: {fixture.trust_root}")
    probe = controller_scripts / "rq03f_b3_hosted_operator_probe.py"
    probe_raw = probe.read_bytes()
    probe_key = "controller:rq03f_b3_hosted_operator_probe"
    fixture.write_protected(probe_key, probe_raw, mode=0o444)
    fixture.build["components"].append(
        {
            "component_id": "rq03f_b3_hosted_operator_probe",
            "component_type": "python_module",
            "inventory_key": probe_key,
            "runtime_path": str(probe.resolve(strict=True)),
            "sha256": sha256_bytes(probe_raw),
        }
    )
    fixture._pin_build(fixture.build)

    fixture.profile["operator_unix_uid"] = operator_uid
    fixture.profile["non_operator_process_unix_uids"] = non_operator_uids
    fixture.profile["created_at"] = "2026-10-10T00:00:00Z"
    fixture.write_protected("authority_profile", canonical_json_bytes(fixture.profile), mode=0o600)

    profile_raw = Path(fixture.entries["authority_profile"]["path"]).read_bytes()
    index_raw = Path(fixture.entries["operation_index"]["path"]).read_bytes()
    profile_path = TRUST_ROOT / "authority-profile.json"
    index_path = TRUST_ROOT / "operation-index.json"
    profile_path.write_bytes(profile_raw)
    index_path.write_bytes(index_raw)
    profile_path.chmod(0o600)
    index_path.chmod(0o600)
    fixture.entries["authority_profile"] = {
        **fixture.entries["authority_profile"],
        "path": str(profile_path),
        "sha256": sha256_bytes(profile_raw),
    }
    fixture.entries["operation_index"] = {
        **fixture.entries["operation_index"],
        "path": str(index_path),
        "sha256": sha256_bytes(index_raw),
    }
    operator_uid, operator_gid = _identity("rq03f-operator")
    operator_trust_parent = TRUST_ROOT.parent
    os.chown(operator_trust_parent, operator_uid, operator_gid)
    operator_trust_parent.chmod(0o700)
    candidate_uid, candidate_gid = _identity("rq03f-candidate")
    os.chown(fixture.run_root, candidate_uid, candidate_gid)
    fixture.run_root.chmod(0o700)
    TRUST_ROOT.chmod(0o700)

    payload = {
        "entries": fixture.entries,
        "run_root": str(fixture.run_root),
        "protected_roots": [str(TRUST_ROOT), str(CONTROLLER_ROOT)],
        "profile_path": str(profile_path),
        "profile_sha256": sha256_bytes(profile_raw),
        "policy_epoch": fixture.profile["policy_epoch"],
        "operation_index_path": str(index_path),
        "controller_allowlist": [
            ["rq03f-intake-controller", "qualification-corpus-intake-controller", "1.0"]
        ],
        "operator_principal": fixture.operator,
        "operator_unix_uid": operator_uid,
        "non_operator_process_unix_uids": non_operator_uids,
    }
    context_path = TRUST_ROOT / "b3-context.json"
    context_raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    context_path.write_bytes(context_raw)
    context_path.chmod(0o600)
    pins = {
        "profile_sha256": sha256_bytes(profile_raw),
        "index_sha256": sha256_bytes(index_raw),
        "build_sha256": fixture.entries["operator_controller_build"]["sha256"],
        "build_inventory_path": fixture.entries["operator_controller_build"]["path"],
        "python_executable": fixture.build["python_runtime"]["python_executable"],
        "operator_uid": operator_uid,
        "non_operator_uids": non_operator_uids,
    }
    print("B3_PREPARED=" + json.dumps(pins, sort_keys=True), flush=True)
    return pins


def _test_provisioning_refuses_preexisting_account() -> None:
    global REUSE_FIXTURE_CREATED
    existing = subprocess.run(["sudo", "-n", "getent", "passwd", "rq03f-candidate"], text=True, capture_output=True, close_fds=True, check=False)
    if existing.returncode == 0:
        raise RuntimeError("refusing to repurpose an existing rq03f-candidate account for the reuse test")
    result = _root_command(
        [
            "useradd",
            "--system",
            "--user-group",
            "--no-log-init",
            "--create-home",
            "--home-dir",
            "/var/lib/rq03f-candidate",
            "--shell",
            "/usr/sbin/nologin",
            "--comment",
            "B3 account reuse fixture",
            "--",
            "rq03f-candidate",
        ],
        label="create disposable pre-existing role-name fixture",
    )
    if result.returncode != 0:
        raise RuntimeError("could not create the pre-existing account refusal fixture")
    REUSE_FIXTURE_CREATED = True
    _root_command(["passwd", "--lock", "--", "rq03f-candidate"], label="lock account reuse fixture")
    _root_command(["chmod", "0700", "--", "/var/lib/rq03f-candidate"], label="restrict account reuse fixture home")
    refused = _root_command(
        ["bash", str(BOUNDARY_SCRIPT), "create-accounts"],
        label="pre-existing role name is refused without reuse",
        expected=1,
    )
    if refused.returncode == 0:
        raise RuntimeError("provisioner accepted a pre-existing Candidate account")
    if subprocess.run(["sudo", "-n", "getent", "passwd", "rq03f-operator"], capture_output=True, close_fds=True).returncode == 0:
        raise RuntimeError("failed account-creation attempt partially created an Operator identity")
    removed = _root_command(["userdel", "--remove", "--", "rq03f-candidate"], label="remove pre-existing account fixture")
    if removed.returncode != 0:
        raise RuntimeError("could not remove the pre-existing account refusal fixture")
    stale_private_group = subprocess.run(
        ["sudo", "-n", "getent", "group", "rq03f-candidate"],
        text=True,
        capture_output=True,
        close_fds=True,
        check=False,
    )
    if stale_private_group.returncode == 0:
        removed_group = _root_command(
            ["groupdel", "--", "rq03f-candidate"],
            label="remove empty group left by pre-existing account fixture",
        )
        if removed_group.returncode != 0:
            raise RuntimeError("could not remove the pre-existing fixture's private group")
    REUSE_FIXTURE_CREATED = False


def _provision_command(pins: dict, *, trust_root: Path = TRUST_ROOT) -> list[str]:
    return [
        "bash",
        str(BOUNDARY_SCRIPT),
        "provision",
        str(trust_root),
        str(CONTROLLER_ROOT),
        str(RUNTIME_ROOT),
        pins["profile_sha256"],
        pins["index_sha256"],
        pins["build_sha256"],
    ]


def _test_provisioning_path_alias_rejection(pins: dict) -> None:
    profile_path = TRUST_ROOT / "authority-profile.json"
    index_path = TRUST_ROOT / "operation-index.json"
    link_path = TRUST_ROOT / "b3-hardlink-probe"
    symlink_path = CONTROLLER_ROOT / "scripts/b3-symlink-probe"
    before = {
        "profile": _root_sha256(profile_path),
        "index": _root_sha256(index_path),
    }
    _root_command(["ln", str(index_path), str(link_path)], label="insert controlled hardlink preflight fixture")
    _root_command(_provision_command(pins), label="provisioner rejects hard-linked protected file", expected=1)
    _root_command(["rm", "--", str(link_path)], label="remove hardlink preflight fixture")
    _root_command(["ln", "-s", "operator_controller_bootstrap.py", str(symlink_path)], label="insert controlled symlink preflight fixture")
    _root_command(_provision_command(pins), label="provisioner rejects symlink in controller install", expected=1)
    _root_command(["rm", "--", str(symlink_path)], label="remove symlink preflight fixture")
    alias_path = TRUST_DATA_ROOT / "trust-root-alias"
    _root_command(["ln", "-s", str(TRUST_ROOT), str(alias_path)], label="create deployment-root symlink alias fixture")
    _root_command(
        _provision_command(pins, trust_root=alias_path),
        label="provisioner rejects a symlinked trust-root argument",
        expected=1,
    )
    _root_command(["rm", "--", str(alias_path)], label="remove deployment-root symlink alias fixture")
    after = {
        "profile": _root_sha256(profile_path),
        "index": _root_sha256(index_path),
    }
    if before != after:
        FAILURES.append("provisioning path-alias refusals changed protected input bytes")
    else:
        print("B3_TEST=" + json.dumps({"label": "provisioning preflight failures are non-mutating", "result": "PASS", "profile_sha256": after["profile"], "index_sha256": after["index"]}, sort_keys=True), flush=True)


def _install_launcher(pins: dict, *, path: Path, barrier: str | None = None, ready: str | None = None) -> None:
    python_executable = pins["python_executable"]
    build_path = pins["build_inventory_path"]
    bootstrap = CONTROLLER_ROOT / "scripts/operator_controller_bootstrap.py"
    probe = "rq03f_b3_hosted_operator_probe:capture"
    env_lines = [
        "HOME=/var/lib/rq03f-operator",
        "USER=rq03f-operator",
        "LOGNAME=rq03f-operator",
        "PATH=/usr/bin:/bin",
    ]
    if barrier is not None:
        env_lines.extend(
            [f"RQ03F_B3_RELEASE_BARRIER={barrier}", f"RQ03F_B3_READY_FILE={ready}"]
        )
    script = "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            'if [ "$#" -ne 0 ]; then echo "Operator launcher accepts no caller arguments" >&2; exit 64; fi',
            "/usr/bin/env -i " + " ".join(env_lines) + " \\",
            f"  {python_executable} -I -S -B {bootstrap} \\",
            f"  --build-inventory {build_path} --build-sha256 {pins['build_sha256']} \\",
            f"  --controller-root {CONTROLLER_ROOT} --entrypoint {probe}",
            "",
        ]
    )
    if _root_command(["test", "!", "-e", str(path)], label=f"fresh launcher path:{path.name}").returncode != 0:
        raise RuntimeError(f"refusing to overwrite existing launcher path: {path}")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as stream:
        stream.write(script)
        temp_path = Path(stream.name)
    try:
        result = _root_command(
            ["install", "-o", "root", "-g", "root", "-m", "0555", str(temp_path), str(path)],
            label=f"install fixed-argument synthetic launcher:{path.name}",
        )
        if result.returncode != 0:
            raise RuntimeError(f"failed to install fixed test launcher: {path}")
        global LAUNCHER_CREATED
        if path == LAUNCHER:
            LAUNCHER_CREATED = True
    finally:
        temp_path.unlink(missing_ok=True)


def _assert_nonzero(user: str, label: str, command: list[str], *, extra_env: dict[str, str] | None = None) -> None:
    _run_as(user, label, command, "nonzero", extra_env=extra_env)


def _verify_effective_permissions() -> None:
    for command, label in (
        (["stat", "-c", "path=%n owner=%u group=%g mode=%a type=%F", str(TRUST_ROOT)], "effective trust-root mode"),
        (["stat", "-c", "path=%n owner=%u group=%g mode=%a type=%F", str(TRUST_ROOT / "authority-profile.json")], "effective profile mode"),
        (["stat", "-c", "path=%n owner=%u group=%g mode=%a type=%F", str(TRUST_ROOT / "operation-index.json")], "effective index mode"),
        (["stat", "-c", "path=%n owner=%u group=%g mode=%a type=%F", str(CONTROLLER_ROOT)], "effective controller mode"),
        (["stat", "-c", "path=%n owner=%g mode=%a type=%F", str(RUNTIME_ROOT)], "effective runtime mode"),
        (["getfacl", "--recursive", "--omit-header", "--absolute-names", "--", str(TRUST_ROOT)], "effective trust ACLs"),
        (["getfacl", "--recursive", "--omit-header", "--absolute-names", "--", str(CONTROLLER_ROOT)], "effective controller ACLs"),
        (["getfacl", "--recursive", "--omit-header", "--absolute-names", "--", str(RUNTIME_ROOT)], "effective runtime ACLs"),
    ):
        result = _root_command(command, label=label)
        if result.returncode != 0:
            FAILURES.append(f"could not capture effective permissions: {label}")


def _capture_pre_provision_permissions() -> None:
    for path, label in (
        (TRUST_ROOT, "pre-provision synthetic TrustContext root"),
        (TRUST_ROOT / "authority-profile.json", "pre-provision synthetic Profile"),
        (TRUST_ROOT / "operation-index.json", "pre-provision synthetic Index"),
        (CONTROLLER_ROOT, "pre-provision controller installation"),
        (RUNTIME_ROOT, "pre-provision Python runtime"),
    ):
        _root_command(
            ["stat", "-c", "path=%n owner=%u group=%g mode=%a type=%F links=%h", str(path)],
            label=label,
        )
    for path, label in (
        (TRUST_ROOT, "pre-provision trust-root ACL"),
        (TRUST_ROOT / "operation-index.json", "pre-provision Index ACL"),
        (CONTROLLER_ROOT, "pre-provision controller ACL"),
        (RUNTIME_ROOT, "pre-provision runtime ACL"),
    ):
        _root_command(["getfacl", "--omit-header", "--absolute-names", "--", str(path)], label=label)


def _operator_bootstrap_command(pins: dict, expected_sha: str | None = None) -> list[str]:
    return [
        pins["python_executable"],
        "-I",
        "-S",
        "-B",
        str(CONTROLLER_ROOT / "scripts/operator_controller_bootstrap.py"),
        "--build-inventory",
        pins["build_inventory_path"],
        "--build-sha256",
        expected_sha or pins["build_sha256"],
        "--controller-root",
        str(CONTROLLER_ROOT),
        "--entrypoint",
        "rq03f_b3_hosted_operator_probe:capture",
    ]


def _run_identity_matrix() -> None:
    identity_code = (
        "import json,os; s=open('/proc/self/status',encoding='ascii').read().splitlines(); "
        "caps={x.split(':',1)[0]:x.split(':',1)[1].strip() for x in s if x.startswith(('CapEff:','CapBnd:','NoNewPrivs:'))}; "
        "fds=[]; "
        "[(fds.append(os.readlink('/proc/self/fd/'+n))) for n in os.listdir('/proc/self/fd') "
        "if n.isdigit() and int(n)>2 and os.path.exists('/proc/self/fd/'+n)]; "
        "print(json.dumps({'uid':os.getuid(),'euid':os.geteuid(),'gid':os.getgid(),'groups':os.getgroups(),'caps':caps,'fd_targets':fds},sort_keys=True)); "
        "assert os.getuid()==os.geteuid()!=0; assert caps.get('NoNewPrivs')=='1'; "
        "assert int(caps.get('CapEff','0'),16)==0 and int(caps.get('CapBnd','0'),16)==0; "
        f"assert not any({str(TRUST_ROOT)!r} in p for p in fds)"
    )
    for user in ROLE_USERS:
        expected_gid = _identity(user)[1]
        code = identity_code + f"; assert os.getgid()=={expected_gid}; assert not os.getgroups()"
        _run_as(user, f"real isolated process identity:{user}", ["/usr/bin/python3", "-c", code], 0)


def _verify_role_denials(pins: dict) -> None:
    before_index = _root_sha256(TRUST_ROOT / "operation-index.json")
    index_path = str(TRUST_ROOT / "operation-index.json")
    profile_path = str(TRUST_ROOT / "authority-profile.json")
    build_path = str(TRUST_ROOT / "operator_controller_build.bin")
    context_path = str(TRUST_ROOT / "b3-context.json")
    controller_module = str(CONTROLLER_ROOT / "scripts/qualification_corpus_intake.py")
    runtime_executable = str(RUNTIME_ROOT / "bin/python")
    open_code = "import os,sys; print(f'uid={os.getuid()} euid={os.geteuid()}',flush=True); open(sys.argv[1],'rb').read(1)"
    append_code = "import os,sys; print(f'uid={os.getuid()} euid={os.geteuid()}',flush=True); fd=os.open(sys.argv[1],os.O_WRONLY|os.O_APPEND); os.close(fd)"
    for user in NON_OPERATOR_USERS:
        _run_direct_sudo_probe(user)
        for target, label in (
            (index_path, "index"),
            (profile_path, "profile"),
            (build_path, "build inventory"),
            (context_path, "TrustContext launch configuration"),
        ):
            _assert_nonzero(user, f"{user} cannot read protected {label}", ["/usr/bin/python3", "-c", open_code, target])
        _assert_nonzero(user, f"{user} cannot append protected index", ["/usr/bin/python3", "-c", append_code, index_path])
        _assert_nonzero(user, f"{user} cannot create protected evidence", ["/usr/bin/python3", "-c", "import os,sys; open(sys.argv[1],'xb').write(b'candidate')", str(TRUST_ROOT / f"forged-{user}.json")])
        _assert_nonzero(user, f"{user} cannot modify installed controller code", ["/usr/bin/python3", "-c", append_code, controller_module])
        _assert_nonzero(user, f"{user} cannot replace protected Python runtime", ["/usr/bin/python3", "-c", append_code, runtime_executable])

    candidate_home = pwd.getpwnam("rq03f-candidate").pw_dir
    symlink = str(Path(candidate_home) / "protected-index-link")
    hardlink = str(Path(candidate_home) / "protected-index-hardlink")
    replacement = str(Path(candidate_home) / "replacement-index.json")
    moved = str(Path(candidate_home) / "moved-trust-root")
    link_code = "import os,sys; os.symlink(sys.argv[1],sys.argv[2]); open(sys.argv[2],'rb').read(1)"
    hardlink_code = "import os,sys; os.link(sys.argv[1],sys.argv[2])"
    replace_code = "import os,sys; open(sys.argv[2],'wb').write(b'forged'); os.replace(sys.argv[2],sys.argv[1])"
    traversal = str(TRUST_ROOT / ".." / "trust" / "operation-index.json")
    _assert_nonzero("rq03f-candidate", "symlink cannot read protected index", ["/usr/bin/python3", "-c", link_code, index_path, symlink])
    _assert_nonzero("rq03f-candidate", "hardlink cannot alias protected index", ["/usr/bin/python3", "-c", hardlink_code, index_path, hardlink])
    _assert_nonzero("rq03f-candidate", "candidate cannot replace protected index", ["/usr/bin/python3", "-c", replace_code, index_path, replacement])
    _assert_nonzero("rq03f-candidate", "candidate cannot unlink protected index", ["/usr/bin/python3", "-c", "import os,sys; os.unlink(sys.argv[1])", index_path])
    _assert_nonzero("rq03f-candidate", "path traversal cannot read protected index", ["/usr/bin/python3", "-c", open_code, traversal])
    _assert_nonzero("rq03f-candidate", "candidate cannot rename protected directory", ["/usr/bin/python3", "-c", "import os,sys; os.rename(sys.argv[1],sys.argv[2])", str(TRUST_ROOT), moved])
    _assert_nonzero("rq03f-candidate", "candidate cannot create protected subdirectory", ["/usr/bin/python3", "-c", "import os,sys; os.mkdir(sys.argv[1])", str(TRUST_ROOT / "forged-dir")])
    _assert_nonzero("rq03f-candidate", "candidate has no sudo authority", ["sudo", "-n", "true"])
    fake_profile = Path(candidate_home) / "self-profile.json"
    fake_index = Path(candidate_home) / "self-index.json"
    fake_build = Path(candidate_home) / "self-controller-build.json"
    fake_build_bytes = b'{"build_inventory_version":"1.1"}'
    _run_as(
        "rq03f-candidate",
        "G: Candidate creates its own Profile, Index and Build Inventory files",
        [
            "/usr/bin/python3",
            "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('{}'); "
            "pathlib.Path(sys.argv[2]).write_text('{}'); "
            "pathlib.Path(sys.argv[3]).write_bytes(b'{\"build_inventory_version\":\"1.1\"}')",
            str(fake_profile),
            str(fake_index),
            str(fake_build),
        ],
        0,
    )
    _assert_nonzero(
        "rq03f-candidate",
        "G: fixed launcher rejects Candidate-selected Profile, Index, Build and TrustContext arguments",
        [
            str(LAUNCHER),
            "--profile",
            str(fake_profile),
            "--operation-index",
            str(fake_index),
            "--build-inventory",
            str(fake_build),
            "--trust-context",
            str(Path(candidate_home) / "self-context.json"),
        ],
    )
    _assert_nonzero("rq03f-candidate", "I: intake fails closed without the pinned Operator UID and private TrustContext", [str(LAUNCHER)])
    own_build_command = [
        runtime_executable,
        "-I",
        "-S",
        "-B",
        str(CONTROLLER_ROOT / "scripts/operator_controller_bootstrap.py"),
        "--build-inventory",
        str(fake_build),
        "--build-sha256",
        pins["build_sha256"],
        "--controller-root",
        str(CONTROLLER_ROOT),
        "--entrypoint",
        "rq03f_b3_hosted_operator_probe:capture",
    ]
    own_build_result = _run_as(
        "rq03f-candidate",
        "G: Candidate-selected Build Inventory and bootstrap arguments fail closed",
        own_build_command,
        "nonzero",
    )
    if "Owner-pinned controller build inventory SHA mismatch" not in own_build_result.stderr:
        FAILURES.append("Candidate-selected Build Inventory failed for an unexpected reason")
    after_index = _root_sha256(TRUST_ROOT / "operation-index.json")
    if after_index != before_index:
        FAILURES.append("Candidate privilege-boundary probes changed the protected operation index")
    else:
        print("B3_TEST=" + json.dumps({"label": "C-G/I: Candidate, Author, Reviewer and Approver denials preserve Index bytes", "index_sha256": after_index, "result": "PASS"}, sort_keys=True), flush=True)


def _change_synthetic_profile(action: str, profile_path: Path, context_path: Path) -> None:
    code = r'''import hashlib,json,os,sys
profile_path,context_path,action=sys.argv[1:]
with open(profile_path,"rb") as stream: profile=json.load(stream)
with open(context_path,"rb") as stream: payload=json.load(stream)
if action == "rotate":
    profile["policy_epoch"] += 1
elif action == "revoke":
    principal=profile["qualification_corpus_custodian_principal"]
    rows=[row for row in profile["roles"] if row["principal_id"] == principal]
    if len(rows) != 1: raise SystemExit("synthetic custodian role is missing or duplicated")
    rows[0]["revoked_at"]="2000-01-01T00:00:00Z"
    rows[0]["revocation_reason"]="B3 synthetic revocation probe"
else:
    raise SystemExit("unknown synthetic profile mutation")
raw=json.dumps(profile,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
digest=hashlib.sha256(raw).hexdigest()
payload["profile_sha256"]=digest
payload["entries"]["authority_profile"]["sha256"]=digest
with open(profile_path,"wb") as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())
with open(context_path,"wb") as stream: stream.write(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")); stream.flush(); os.fsync(stream.fileno())
print(json.dumps({"action":action,"profile_sha256":digest,"context_policy_epoch":payload["policy_epoch"],"profile_policy_epoch":profile["policy_epoch"]},sort_keys=True))
'''
    result = _root_command(
        ["python3", "-c", code, str(profile_path), str(context_path), action],
        label=f"mutate synthetic protected Profile for {action} fail-closed test",
    )
    if result.returncode != 0:
        raise RuntimeError(f"could not prepare synthetic Profile {action} test")


def _verify_epoch_rotation_and_revocation(pins: dict) -> None:
    profile_path = TRUST_ROOT / "authority-profile.json"
    context_path = TRUST_ROOT / "b3-context.json"
    index_path = TRUST_ROOT / "operation-index.json"
    before_index = _root_sha256(index_path)
    backup_dir_result = _root_command(
        ["mktemp", "-d", "-p", "/tmp", f"rq03f-b3-authority-{uuid.uuid4().hex[:12]}.XXXXXX"],
        label="create private rollback directory for synthetic authority tests",
    )
    if backup_dir_result.returncode != 0:
        raise RuntimeError("could not create private synthetic authority rollback directory")
    backup_dir = Path(backup_dir_result.stdout.strip().splitlines()[-1])
    backup_profile = backup_dir / "profile.original"
    backup_context = backup_dir / "context.original"
    profile_backup_result = _root_command(["cp", "--", str(profile_path), str(backup_profile)], label="back up exact synthetic Profile bytes")
    context_backup_result = _root_command(["cp", "--", str(context_path), str(backup_context)], label="back up exact synthetic TrustContext bytes")
    if profile_backup_result.returncode != 0 or context_backup_result.returncode != 0:
        _root_command(["rm", "-rf", "--", str(backup_dir)], label="remove incomplete synthetic authority backup")
        raise RuntimeError("could not back up exact synthetic authority files before rotation tests")
    try:
        _change_synthetic_profile("rotate", profile_path, context_path)
        rotated = _run_as(
            "rq03f-operator",
            "J: old context is rejected after Profile policy epoch rotation",
            [str(LAUNCHER)],
            "nonzero",
        )
        if "stale policy epoch: INVALID authority" not in rotated.stderr:
            FAILURES.append("epoch-rotation check failed for an unexpected reason")
        _root_command(["cp", "--", str(backup_profile), str(profile_path)], label="restore synthetic Profile after epoch check")
        _root_command(["cp", "--", str(backup_context), str(context_path)], label="restore synthetic TrustContext after epoch check")

        _change_synthetic_profile("revoke", profile_path, context_path)
        revoked = _run_as(
            "rq03f-operator",
            "J: revoked corpus custodian cannot perform protected intake",
            [str(LAUNCHER)],
            "nonzero",
        )
        if "revoked principal role" not in revoked.stderr:
            FAILURES.append("revocation check failed for an unexpected reason")
    finally:
        profile_restore = _root_command(["cp", "--", str(backup_profile), str(profile_path)], label="restore exact synthetic Profile bytes")
        context_restore = _root_command(["cp", "--", str(backup_context), str(context_path)], label="restore exact synthetic TrustContext bytes")
        if profile_restore.returncode != 0 or context_restore.returncode != 0:
            FAILURES.append("could not restore exact synthetic Profile and TrustContext bytes")
        _root_command(["rm", "-rf", "--", str(backup_dir)], label="remove private authority rollback files")
    after_index = _root_sha256(index_path)
    if after_index != before_index:
        FAILURES.append("epoch or revocation fail-closed test changed the protected index")
    else:
        print("B3_TEST=" + json.dumps({"label": "J: epoch rotation and authority revocation preserve Index bytes", "index_sha256": after_index, "result": "PASS"}, sort_keys=True), flush=True)


def _setup_poison_path() -> str:
    candidate_home = pwd.getpwnam("rq03f-candidate").pw_dir
    poison = str(Path(candidate_home) / "poison")
    poison_code = (
        "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.mkdir(); "
        "(p/'semantic_scope_records.py').write_text(\"from pathlib import Path\\nPath('/tmp/rq03f-b3-shadow-imported').write_text('loaded')\\n\"); "
        "(p/'jsonschema.py').write_text(\"from pathlib import Path\\nPath('/tmp/rq03f-b3-shadow-imported').write_text('loaded')\\n\")"
    )
    result = _run_as("rq03f-candidate", "candidate creates malicious PYTHONPATH modules", ["/usr/bin/python3", "-c", poison_code, poison], 0)
    if result.returncode != 0:
        raise RuntimeError("could not prepare candidate-controlled module shadows")
    return poison


def _run_operator_success(pins: dict, label: str, *, poisoned_path: str | None = None) -> subprocess.CompletedProcess[str]:
    if poisoned_path:
        return _run_as(
            "rq03f-operator",
            label,
            _operator_bootstrap_command(pins),
            0,
            extra_env={"PYTHONPATH": poisoned_path},
        )
    return _run_as("rq03f-operator", label, [str(LAUNCHER)], 0)


def _run_concurrent_stale_writers(pins: dict) -> None:
    barrier = TRUST_ROOT / "b3-concurrency-release"
    ready_paths = [TRUST_ROOT / "b3-concurrency-ready-a", TRUST_ROOT / "b3-concurrency-ready-b"]
    for path in [barrier, *ready_paths]:
        _root_command(["rm", "-f", str(path)], label=f"clear synthetic concurrency marker:{path.name}")
    launchers = [STAGE_ROOT / "concurrent-a", STAGE_ROOT / "concurrent-b"]
    for launcher, ready in zip(launchers, ready_paths, strict=True):
        _install_launcher(pins, path=launcher, barrier=str(barrier), ready=str(ready))
    processes = []
    for launcher in launchers:
        command, env_keys = _setpriv_command("rq03f-operator", [str(launcher)])
        process = subprocess.Popen(command, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
        processes.append((launcher.name, process, env_keys))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        ready_checks = [
            subprocess.run(["sudo", "-n", "test", "-e", str(path)], capture_output=True, close_fds=True).returncode == 0
            for path in ready_paths
        ]
        if all(ready_checks):
            break
        if any(process.poll() is not None for _name, process, _keys in processes):
            break
        time.sleep(0.02)
    ready = all(
        subprocess.run(["sudo", "-n", "test", "-e", str(path)], capture_output=True, close_fds=True).returncode == 0
        for path in ready_paths
    )
    if ready:
        _root_command(["touch", str(barrier)], label="release two stale-snapshot Operator writers")
    else:
        FAILURES.append("concurrent Operator writers did not both reach the snapshot barrier")
        _root_command(["touch", str(barrier)], label="release incomplete concurrency barrier")
    results = []
    for name, process, env_keys in processes:
        try:
            stdout, stderr = process.communicate(timeout=40)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            FAILURES.append(f"concurrent writer timed out: {name}")
        results.append((name, process.returncode, stdout, stderr, env_keys))
    success_count = sum(code == 0 for _name, code, _out, _err, _keys in results)
    blocked_count = sum(code != 0 for _name, code, _out, _err, _keys in results)
    for name, code, stdout, stderr, env_keys in results:
        passed = success_count == 1 and blocked_count == 1
        if not passed:
            FAILURES.append(f"concurrent stale snapshot expected one success/one fail; {name} exit={code}")
        print(
            "B3_TEST="
            + json.dumps(
                {
                    "label": f"concurrent append-only stale-snapshot writer:{name}",
                    "user": "rq03f-operator",
                    "uid": _identity("rq03f-operator")[0],
                    "command": [str(launchers[0] if name == "concurrent-a" else launchers[1])],
                    "environment_overrides": list(env_keys),
                    "exit_code": code,
                    "expected": "one concurrent writer commits and the stale writer fails closed",
                    "result": "PASS" if passed else "FAIL",
                    "stdout": stdout.strip()[-3000:],
                    "stderr": stderr.strip()[-1500:],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if success_count == 1 and blocked_count == 1:
        failed_stale = next(err for _name, code, _out, err, _keys in results if code != 0)
        if "changed raw-byte binding: operation_index" not in failed_stale:
            FAILURES.append("concurrent stale writer failed for an unexpected reason")


def _verify_wrong_build_pin(pins: dict) -> None:
    wrong = "0" * 64 if pins["build_sha256"] != "0" * 64 else "f" * 64
    before = _root_sha256(TRUST_ROOT / "operation-index.json")
    result = _run_as(
        "rq03f-operator",
        "mismatched Controller Build Pin fails closed",
        _operator_bootstrap_command(pins, expected_sha=wrong),
        "nonzero",
    )
    if "Owner-pinned controller build inventory SHA mismatch" not in result.stderr:
        FAILURES.append("mismatched Build Pin failed for an unexpected reason")
    after = _root_sha256(TRUST_ROOT / "operation-index.json")
    if after != before:
        FAILURES.append("wrong Controller Build Pin changed the protected operation index")
    else:
        print("B3_TEST=" + json.dumps({"label": "wrong build pin leaves index unchanged", "result": "PASS", "index_sha256": after}, sort_keys=True), flush=True)


def _read_final_index() -> dict:
    code = (
        "import hashlib,json,sys; raw=open(sys.argv[1],'rb').read(); i=json.loads(raw); "
        "print(json.dumps({'index_sha256':hashlib.sha256(raw).hexdigest(),'author_rows':len(i['authors']),"
        "'qualification_intake_rows':len(i['qualification_corpus_intakes']),'receipts':len(i['receipts']),"
        "'adjudications':len(i['adjudications']),'qualification_runs':len(i['qualification_runs'])},sort_keys=True))"
    )
    result_run = _root_command(["python3", "-c", code, str(TRUST_ROOT / "operation-index.json")], label="read final synthetic Index 1.1 summary")
    if result_run.returncode != 0:
        raise RuntimeError("could not inspect final synthetic protected index")
    result = json.loads(result_run.stdout.splitlines()[-1])
    print("B3_FINAL_INDEX=" + json.dumps(result, sort_keys=True), flush=True)
    if (
        result["author_rows"] != 0
        or result["qualification_intake_rows"] != 3
        or result["receipts"] != 0
        or result["adjudications"] != 0
        or result["qualification_runs"] != 0
    ):
        FAILURES.append("synthetic final Index 1.1 rows differ from three intakes, zero authors, and zero production artifacts")
    return result


def _test_suite(pins: dict) -> None:
    global MARKER_CREATED
    print("B3_PHASE=privileged_provisioning_complete", flush=True)
    _verify_effective_permissions()
    _run_identity_matrix()
    operator_uid = _identity("rq03f-operator")[0]
    operator_read = (
        "import hashlib,json,os,sys; paths=sys.argv[1:]; "
        "print(json.dumps({'uid':os.getuid(),'euid':os.geteuid(),'readable':[hashlib.sha256(open(p,'rb').read()).hexdigest() for p in paths]}))"
    )
    _run_as(
        "rq03f-operator",
        "A: Operator reads synthetic protected Profile and Index",
        ["/usr/bin/python3", "-c", operator_read, str(TRUST_ROOT / "authority-profile.json"), str(TRUST_ROOT / "operation-index.json"), pins["build_inventory_path"]],
        0,
    )
    _verify_wrong_build_pin(pins)
    poison = _setup_poison_path()
    if _root_command(["test", "!", "-e", str(MARKER)], label="module-shadow marker starts absent").returncode != 0:
        FAILURES.append("module-shadow marker path existed before the hosted test")
    _run_operator_success(pins, "B/K: Operator performs real protected qualification-only intake with hostile PYTHONPATH", poisoned_path=poison)
    if MARKER.exists():
        MARKER_CREATED = True
        FAILURES.append("malicious PYTHONPATH module executed in isolated Operator controller")
    else:
        print("B3_TEST=" + json.dumps({"label": "H: hostile PYTHONPATH and module shadow ignored by Python -I", "result": "PASS", "marker_exists": False}, sort_keys=True), flush=True)
    _run_operator_success(pins, "B/K: fresh Operator context appends second custody-only intake")
    _verify_epoch_rotation_and_revocation(pins)
    _run_concurrent_stale_writers(pins)
    _verify_role_denials(pins)
    _read_final_index()
    print(f"B3_SUMMARY=failures:{len(FAILURES)} operator_uid:{operator_uid}", flush=True)


def _cleanup() -> bool:
    global STAGE_CREATED, TRUST_DATA_CREATED, LAUNCHER_CREATED, REUSE_FIXTURE_CREATED, MARKER_CREATED
    cleanup_failed = False
    cleanup_paths: list[Path] = []
    if LAUNCHER_CREATED:
        cleanup_paths.append(LAUNCHER)
    if STAGE_CREATED:
        cleanup_paths.append(STAGE_ROOT)
    if TRUST_DATA_CREATED:
        cleanup_paths.append(TRUST_DATA_ROOT)
    if MARKER_CREATED:
        cleanup_paths.append(MARKER)
    for path in cleanup_paths:
        result = subprocess.run(
            ["sudo", "-n", "rm", "-rf", "--", str(path)],
            text=True,
            capture_output=True,
            close_fds=True,
            check=False,
        )
        if result.returncode != 0:
            cleanup_failed = True
            print(f"B3_CLEANUP_FAIL path={path} exit={result.returncode} {result.stderr.strip()}", flush=True)
        else:
            print(f"B3_CLEANUP_OK path={path}", flush=True)
    for user in reversed(ROLE_USERS):
        if user not in CREATED_ACCOUNTS:
            continue
        try:
            record = pwd.getpwnam(user)
        except KeyError:
            continue
        if record.pw_gecos != "RQ03F temporary isolated role":
            cleanup_failed = True
            print(f"B3_CLEANUP_REFUSED unexpected account identity for {user}", flush=True)
            continue
        result = subprocess.run(
            ["sudo", "-n", "userdel", "--remove", "--", user],
            text=True,
            capture_output=True,
            close_fds=True,
            check=False,
        )
        if result.returncode != 0:
            cleanup_failed = True
            print(f"B3_CLEANUP_FAIL userdel={user} exit={result.returncode} {result.stderr.strip()}", flush=True)
        subprocess.run(["sudo", "-n", "groupdel", "--", user], text=True, capture_output=True, close_fds=True, check=False)
        print(f"B3_CLEANUP_OK account={user}", flush=True)
    if REUSE_FIXTURE_CREATED:
        user_record = subprocess.run(["sudo", "-n", "getent", "passwd", "rq03f-candidate"], text=True, capture_output=True, close_fds=True, check=False)
        if user_record.returncode == 0 and "B3 account reuse fixture" in user_record.stdout:
            subprocess.run(["sudo", "-n", "userdel", "--remove", "--", "rq03f-candidate"], text=True, capture_output=True, close_fds=True, check=False)
            subprocess.run(["sudo", "-n", "groupdel", "--", "rq03f-candidate"], text=True, capture_output=True, close_fds=True, check=False)
        else:
            cleanup_failed = True
            print("B3_CLEANUP_REFUSED unexpected pre-existing role fixture identity", flush=True)
        REUSE_FIXTURE_CREATED = False
        MARKER_CREATED = False
    return not cleanup_failed


def run_hosted_suite() -> int:
    global STAGE_CREATED, TRUST_DATA_CREATED
    try:
        if os.geteuid() == 0:
            raise RuntimeError("run the orchestrator as the unprivileged GitHub Actions runner user")
        preflight = subprocess.run(["sudo", "-n", "true"], text=True, capture_output=True, close_fds=True, check=False)
        if preflight.returncode != 0:
            raise RuntimeError("GitHub runner does not expose the expected temporary sudo provisioning boundary")

        _test_provisioning_refuses_preexisting_account()
        account_result = _root_command(["bash", str(BOUNDARY_SCRIPT), "create-accounts"], label="create five fresh independent role identities")
        if account_result.returncode != 0:
            raise RuntimeError("fresh OS role provisioning failed")
        for user in ROLE_USERS:
            pwd.getpwnam(user)
            CREATED_ACCOUNTS.append(user)

        _stage_roots()
        if _root_command(["test", "!", "-e", str(TRUST_DATA_ROOT)], label="fresh synthetic TrustContext path").returncode != 0:
            raise RuntimeError(f"refusing to overwrite pre-existing synthetic TrustContext path: {TRUST_DATA_ROOT}")
        TRUST_DATA_CREATED = True
        prepare_result = _root_command(
            [str(RUNTIME_ROOT / "bin/python"), "-B", str(SCRIPT), "--prepare"],
            label="materialize temporary synthetic TrustContext and exact pins",
        )
        if prepare_result.returncode != 0:
            raise RuntimeError("synthetic TrustContext preparation failed")
        prepared = next(
            (line[len("B3_PREPARED="):] for line in prepare_result.stdout.splitlines() if line.startswith("B3_PREPARED=")),
            None,
        )
        if prepared is None:
            raise RuntimeError("synthetic TrustContext preparation did not return pin data")
        pins = json.loads(prepared)
        print("B3_SYNTHETIC_PINS=" + json.dumps(pins, sort_keys=True), flush=True)

        _test_provisioning_path_alias_rejection(pins)
        _capture_pre_provision_permissions()
        provision_result = _root_command(
            _provision_command(pins),
            label="apply and verify protected operator boundary",
        )
        if provision_result.returncode != 0:
            raise RuntimeError("Operator boundary provisioning failed")

        _install_launcher(pins, path=LAUNCHER)
        _test_suite(pins)
    except BaseException as exc:
        FAILURES.append(f"hosted isolation orchestration error: {type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        cleanup_ok = _cleanup()
        if not cleanup_ok:
            FAILURES.append("temporary accounts or files were not fully removed")

    print("B3_OVERALL=" + ("PASS" if not FAILURES else "BLOCKED"), flush=True)
    for failure in FAILURES:
        print("B3_FAILURE=" + failure, flush=True)
    return 0 if not FAILURES else 1


def _prepare_only() -> int:
    try:
        _prepare_fixture()
        return 0
    except BaseException:
        traceback.print_exc()
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    return _prepare_only() if args.prepare else run_hosted_suite()


if __name__ == "__main__":
    raise SystemExit(main())
