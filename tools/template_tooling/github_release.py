"""GitHub Release adapter with a fail-closed, fake-testable transaction."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from .manifest import sha256_file
from .models import RELEASE_TOOL_VERSION, TemplateToolError, parse_semver
from .paths import atomic_write_text, remove_path_or_raise, validate_windows_component
from .release import (
    RELEASE_PLAN_SCHEMA_VERSION,
    _load_json_object,
    _require_sha,
    _strict_archive_name,
    _verify_release_archive_matches_source_snapshot,
    release_source_snapshot_for_commit,
    verify_release_bundle,
)


@dataclass(frozen=True)
class GitHubRepositoryIdentity:
    host: str
    owner: str
    name: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


def _repository_parts(value: str) -> tuple[str, str]:
    normalized = value.strip().strip("/")
    if normalized.casefold().endswith(".git"):
        normalized = normalized[:-4]
    parts = normalized.split("/")
    if len(parts) != 2 or any(not part or part in {".", ".."} or re.search(r"\s", part) for part in parts):
        raise TemplateToolError("GitHub repository must use owner/name form")
    return parts[0], parts[1]


def _parse_repository_argument(repository: str) -> GitHubRepositoryIdentity:
    if not isinstance(repository, str) or not repository.strip():
        raise TemplateToolError("GitHub repository must use owner/name form")
    owner, name = _repository_parts(repository)
    return GitHubRepositoryIdentity(host="github.com", owner=owner, name=name)


def _origin_repository_identity(root: Path) -> GitHubRepositoryIdentity:
    result = _run(["git", "config", "--get", "remote.origin.url"], root, check=False)
    remote = result.stdout.strip()
    if result.returncode != 0 or not remote:
        details = result.stderr.strip() or result.stdout.strip()
        raise TemplateToolError(f"cannot resolve GitHub origin repository: {details or 'origin is missing'}")

    scp_match = re.fullmatch(r"[^@/:]+@(?P<host>[^:]+):(?P<path>.+)", remote)
    if scp_match:
        host = scp_match.group("host")
        path = scp_match.group("path")
    else:
        try:
            parsed = urlsplit(remote)
            host = parsed.hostname or ""
            path = parsed.path
        except ValueError as exc:
            raise TemplateToolError("malformed GitHub origin repository URL") from exc
        if parsed.scheme.casefold() not in {"https", "ssh"}:
            raise TemplateToolError("malformed GitHub origin repository URL")
    if host.casefold() != "github.com":
        raise TemplateToolError("unsupported GitHub origin host for release publication")
    try:
        owner, name = _repository_parts(path)
    except TemplateToolError as exc:
        raise TemplateToolError("malformed GitHub origin repository URL") from exc
    return GitHubRepositoryIdentity(host=host.casefold(), owner=owner, name=name)


def _assert_repository_identity(root: Path, requested_repository: str | None) -> GitHubRepositoryIdentity:
    origin = _origin_repository_identity(root)
    if requested_repository is None:
        return origin
    requested = _parse_repository_argument(requested_repository)
    if (
        requested.host.casefold() != origin.host.casefold()
        or requested.owner.casefold() != origin.owner.casefold()
        or requested.name.casefold() != origin.name.casefold()
    ):
        raise TemplateToolError(
            "GitHub repository does not match origin: "
            f"origin={origin.slug}, requested={requested.slug}"
        )
    return origin


class GitHubReleaseClient(Protocol):
    """The small remote surface required by the publication transaction."""

    def tag_exists(self, tag: str) -> bool: ...

    def tag_target(self, tag: str) -> str: ...

    def tag_annotation(self, tag: str) -> dict[str, Any]: ...

    def release_exists(self, tag: str) -> bool: ...

    def release_tag(self, tag: str) -> str: ...

    def release_identity(self, tag: str) -> dict[str, Any]: ...

    def asset_names(self, tag: str) -> set[str]: ...

    def create_tag(self, tag: str, source_commit: str, message: str) -> None: ...

    def delete_tag(self, tag: str) -> None: ...

    def create_release(self, tag: str, name: str, body: str, prerelease: bool) -> None: ...

    def delete_release(self, tag: str) -> None: ...

    def upload_asset(self, tag: str, path: Path) -> None: ...

    def delete_asset(self, tag: str, name: str) -> None: ...

    def download_asset(self, tag: str, name: str, destination: Path) -> Path: ...


def _run(command: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip()
        raise TemplateToolError(f"command failed ({result.returncode}): {' '.join(command)}: {details}")
    return result


class GhCliGitHubReleaseClient:
    """Production adapter using git and the GitHub CLI without clobbering."""

    def __init__(self, root: Path, *, repository: str | None = None) -> None:
        self.root = root.resolve()
        self.repository_identity = _assert_repository_identity(self.root, repository)
        self.repository = self.repository_identity.slug

    def _gh_repo(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        command = ["gh", *arguments, "--repo", self.repository]
        return _run(command, self.root, check=check)

    def _gh_api(
        self,
        endpoint: str,
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        prefix = f"repos/{self.repository_identity.owner}/{self.repository_identity.name}/"
        if (
            not endpoint.startswith(prefix)
            or any(character in endpoint for character in "\\?#%\r\n")
            or any(component in {"", ".", ".."} for component in endpoint.split("/"))
        ):
            raise TemplateToolError("GitHub API endpoint is not a safe repository-scoped path")
        command = [
            "gh",
            "api",
            "--hostname",
            self.repository_identity.host,
            endpoint,
        ]
        return _run(command, self.root, check=check)

    def _tag_ref_endpoint(self, tag: str) -> str:
        components = tag.split("/")
        if not components or any(
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", component) for component in components
        ):
            raise TemplateToolError(f"GitHub tag contains an unsafe ref path: {tag}")
        encoded_tag = "/".join(quote(component, safe="-._~") for component in components)
        return f"repos/{self.repository_identity.owner}/{self.repository_identity.name}/git/ref/tags/{encoded_tag}"

    def tag_exists(self, tag: str) -> bool:
        result = _run(["git", "ls-remote", "--exit-code", "origin", f"refs/tags/{tag}"], self.root, check=False)
        if result.returncode == 0:
            return True
        if result.returncode == 2:
            return False
        details = result.stderr.strip() or result.stdout.strip()
        raise TemplateToolError(f"cannot check remote tag {tag}: {details}")

    def tag_target(self, tag: str) -> str:
        return str(self.tag_annotation(tag)["target"]).lower()

    def tag_annotation(self, tag: str) -> dict[str, Any]:
        reference_result = self._gh_api(self._tag_ref_endpoint(tag))
        try:
            reference = json.loads(reference_result.stdout)
            tag_object = reference["object"]
            object_id = str(tag_object["sha"])
            object_type = str(tag_object["type"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise TemplateToolError("GitHub tag reference returned invalid JSON") from exc
        if object_type != "tag":
            raise TemplateToolError(f"remote tag is not annotated: {tag}")
        if not re.fullmatch(r"[0-9a-fA-F]{40}", object_id):
            raise TemplateToolError("GitHub tag reference returned an invalid tag object id")
        tag_result = self._gh_api(
            f"repos/{self.repository_identity.owner}/{self.repository_identity.name}/git/tags/{object_id}"
        )
        try:
            payload = json.loads(tag_result.stdout)
            target = str(payload["object"]["sha"])
            message = payload["message"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise TemplateToolError("GitHub annotated tag returned invalid JSON") from exc
        if not target or not isinstance(message, str):
            raise TemplateToolError("GitHub annotated tag has incomplete identity")
        return {"object_id": object_id, "target": target.lower(), "message": message}

    def release_exists(self, tag: str) -> bool:
        result = self._gh_repo("release", "view", tag, check=False)
        if result.returncode == 0:
            return True
        details = f"{result.stderr}\n{result.stdout}".strip()
        if re.search(r"(?:not found|404)", details, re.IGNORECASE):
            return False
        raise TemplateToolError(f"cannot check GitHub Release {tag}: {details}")

    def release_tag(self, tag: str) -> str:
        return str(self.release_identity(tag)["tag"])

    def release_identity(self, tag: str) -> dict[str, Any]:
        try:
            payload = json.loads(
                self._gh_repo("release", "view", tag, "--json", "tagName,body,databaseId").stdout
            )
            value = payload["tagName"]
            body = payload.get("body")
            database_id = payload.get("databaseId")
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise TemplateToolError("gh release view returned invalid tag JSON") from exc
        if not isinstance(value, str) or not value:
            raise TemplateToolError("GitHub Release returned an empty tag name")
        if not isinstance(body, str):
            raise TemplateToolError("GitHub Release returned an invalid body")
        return {"id": database_id, "tag": value, "body": body}

    def asset_names(self, tag: str) -> set[str]:
        result = self._gh_repo("release", "view", tag, "--json", "assets", check=True)
        try:
            payload = json.loads(result.stdout)
            return {str(item["name"]) for item in payload.get("assets", [])}
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise TemplateToolError("gh release view returned invalid asset JSON") from exc

    def create_tag(self, tag: str, source_commit: str, message: str) -> None:
        _run(["git", "tag", "-a", tag, source_commit, "-m", message], self.root)
        try:
            _run(["git", "push", "origin", f"refs/tags/{tag}"], self.root)
        except Exception:
            _run(["git", "tag", "-d", tag], self.root, check=False)
            raise

    def delete_tag(self, tag: str) -> None:
        _run(["git", "push", "origin", f":refs/tags/{tag}"], self.root)
        _run(["git", "tag", "-d", tag], self.root, check=False)

    def create_release(self, tag: str, name: str, body: str, prerelease: bool) -> None:
        notes_file = self.root / ".release-notes.tmp"
        if notes_file.exists() or notes_file.is_symlink():
            raise TemplateToolError("release notes temporary path already exists")
        try:
            atomic_write_text(notes_file, body)
            arguments = ["release", "create", tag, "--title", name, "--notes-file", str(notes_file), "--verify-tag"]
            if prerelease:
                arguments.append("--prerelease")
            self._gh_repo(*arguments)
        finally:
            if notes_file.exists() or notes_file.is_symlink():
                remove_path_or_raise(notes_file)

    def delete_release(self, tag: str) -> None:
        self._gh_repo("release", "delete", tag, "--yes")

    def upload_asset(self, tag: str, path: Path) -> None:
        # No --clobber: a pre-existing or concurrently-created asset fails closed.
        self._gh_repo("release", "upload", tag, str(path))

    def delete_asset(self, tag: str, name: str) -> None:
        self._gh_repo("release", "delete-asset", tag, name, "--yes")

    def download_asset(self, tag: str, name: str, destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=False)
        self._gh_repo("release", "download", tag, "--pattern", name, "--dir", str(destination))
        path = destination / name
        if not path.is_file() or path.is_symlink():
            raise TemplateToolError(f"downloaded release asset is missing: {name}")
        return path


class InMemoryGitHubReleaseClient:
    """Fake adapter for transaction rehearsals and deterministic unit tests."""

    def __init__(self, *, fail_at: str | set[str] | None = None) -> None:
        self.tags: dict[str, dict[str, Any]] = {}
        self.releases: dict[str, dict[str, Any]] = {}
        self.fail_at = fail_at
        self.events: list[str] = []
        self.other_operation_id = "other-publication"
        self._next_release_id = 1

    def _fail(self, event: str) -> None:
        self.events.append(event)
        if event == self.fail_at or (isinstance(self.fail_at, set) and event in self.fail_at):
            raise TemplateToolError(f"injected GitHub adapter failure: {event}")

    def _mutate_then_raise(self, event: str) -> None:
        marker = f"mutate_then_raise:{event}"
        base_event = event.split(":", 1)[0]
        markers = {marker, f"mutate_then_raise:{base_event}"}
        if any(
            candidate == self.fail_at or (isinstance(self.fail_at, set) and candidate in self.fail_at)
            for candidate in markers
        ):
            raise TemplateToolError(f"injected GitHub adapter failure after mutation: {event}")

    def _concurrent_other(self, event: str) -> bool:
        base_event = event.split(":", 1)[0]
        markers = {f"concurrent_other:{event}", f"concurrent_other:{base_event}"}
        return any(
            candidate == self.fail_at or (isinstance(self.fail_at, set) and candidate in self.fail_at)
            for candidate in markers
        )

    def _tag_operation(self, message: str) -> str:
        match = re.search(r"(?m)^Release operation: ([^\r\n]+)$", message)
        return match.group(1) if match else "missing-operation"

    def _tag_message(self, target: str, operation_id: str) -> str:
        return f"Fixture tag\n\nSource commit: {target}\nRelease operation: {operation_id}"

    def _release_body(self, operation_id: str) -> str:
        return f"fixture release\n\n<!-- template-release-operation:{operation_id} -->"

    def tag_exists(self, tag: str) -> bool:
        return tag in self.tags

    def tag_target(self, tag: str) -> str:
        return str(self.tag_annotation(tag)["target"]).lower()

    def tag_annotation(self, tag: str) -> dict[str, Any]:
        if tag not in self.tags:
            raise TemplateToolError(f"fake tag does not exist: {tag}")
        value = self.tags[tag]
        if isinstance(value, str):
            return {"object_id": "legacy-fake-tag", "target": value.lower(), "message": "legacy"}
        return dict(value)

    def release_exists(self, tag: str) -> bool:
        return tag in self.releases

    def release_tag(self, tag: str) -> str:
        return str(self.release_identity(tag)["tag"])

    def release_identity(self, tag: str) -> dict[str, Any]:
        if tag not in self.releases:
            raise TemplateToolError(f"fake release does not exist: {tag}")
        value = self.releases[tag]
        return {
            "id": value.get("id"),
            "tag": value.get("tag", tag),
            "body": value.get("body", ""),
        }

    def asset_names(self, tag: str) -> set[str]:
        return set(self.releases.get(tag, {}).get("assets", {}))

    def create_tag(self, tag: str, source_commit: str, message: str) -> None:
        self._fail("create_tag")
        if tag in self.tags:
            raise TemplateToolError(f"fake tag already exists: {tag}")
        if self._concurrent_other("create_tag"):
            self.tags[tag] = {
                "object_id": uuid.uuid4().hex,
                "target": source_commit,
                "message": self._tag_message(source_commit, self.other_operation_id),
            }
            raise TemplateToolError("remote tag was created concurrently by another publication")
        self.tags[tag] = {
            "object_id": uuid.uuid4().hex,
            "target": source_commit,
            "message": message,
        }
        self._mutate_then_raise("create_tag")

    def delete_tag(self, tag: str) -> None:
        self._fail("delete_tag")
        self.tags.pop(tag, None)

    def create_release(self, tag: str, name: str, body: str, prerelease: bool) -> None:
        self._fail("create_release")
        if tag in self.releases:
            raise TemplateToolError(f"fake release already exists: {tag}")
        if self._concurrent_other("create_release"):
            other_id = self.other_operation_id
            self.releases[tag] = {
                "id": self._next_release_id,
                "name": name,
                "tag": tag,
                "body": self._release_body(other_id),
                "prerelease": prerelease,
                "assets": {},
            }
            self._next_release_id += 1
            raise TemplateToolError("remote Release was created concurrently by another publication")
        else:
            self.releases[tag] = {
                "id": self._next_release_id,
                "name": name,
                "tag": tag,
                "body": body,
                "prerelease": prerelease,
                "assets": {},
            }
        self._next_release_id += 1
        self._mutate_then_raise("create_release")

    def delete_release(self, tag: str) -> None:
        self._fail("delete_release")
        self.releases.pop(tag, None)

    def upload_asset(self, tag: str, path: Path) -> None:
        self._fail(f"upload_asset:{path.name}")
        if tag not in self.releases:
            raise TemplateToolError("fake release does not exist")
        assets = self.releases[tag]["assets"]
        if path.name in assets:
            raise TemplateToolError("fake asset already exists")
        assets[path.name] = path.read_bytes()
        if self._concurrent_other(f"upload_asset:{path.name}"):
            self.releases[tag]["body"] = self._release_body(self.other_operation_id)
            raise TemplateToolError("remote asset was created concurrently by another publication")
        self._mutate_then_raise(f"upload_asset:{path.name}")

    def delete_asset(self, tag: str, name: str) -> None:
        self._fail(f"delete_asset:{name}")
        if tag in self.releases:
            self.releases[tag]["assets"].pop(name, None)

    def download_asset(self, tag: str, name: str, destination: Path) -> Path:
        self._fail(f"download_asset:{name}")
        assets = self.releases.get(tag, {}).get("assets", {})
        if name not in assets:
            raise TemplateToolError(f"fake asset is missing: {name}")
        destination.mkdir(parents=True, exist_ok=False)
        path = destination / name
        path.write_bytes(assets[name])
        return path


def _validate_plan(plan_path: Path, root: Path) -> dict[str, Any]:
    plan = _load_json_object(plan_path, label="release plan")
    expected = {
        "status",
        "schema_version",
        "tool_version",
        "template_id",
        "version",
        "format",
        "tag",
        "release_name",
        "archive",
        "sha256",
        "metadata",
        "assets",
        "archive_sha256",
        "prerelease",
        "source_commit",
        "dry_run",
        "plan",
    }
    if set(plan) != expected:
        missing = sorted(expected - set(plan))
        extra = sorted(set(plan) - expected)
        raise TemplateToolError(f"release plan contract failed; missing={missing}, extra={extra}")
    if plan["status"] != "passed" or plan["schema_version"] != RELEASE_PLAN_SCHEMA_VERSION or plan["tool_version"] != RELEASE_TOOL_VERSION:
        raise TemplateToolError("release plan is not a completed supported plan")
    for key in ("template_id", "version", "format", "tag", "release_name", "archive", "sha256", "metadata", "plan"):
        if not isinstance(plan[key], str) or not plan[key]:
            raise TemplateToolError(f"release plan {key} must be a non-empty string")
    validate_windows_component(plan["template_id"], label="release plan.template_id")
    if str(parse_semver(plan["version"])) != plan["version"]:
        raise TemplateToolError("release plan.version must use canonical ASCII semver spelling")
    if not plan["format"].strip():
        raise TemplateToolError("release plan.format must be a non-empty string")
    if plan["tag"] != f"template/{plan['template_id']}/v{plan['version']}":
        raise TemplateToolError("release plan tag does not match template identity")
    if plan["release_name"] != f"{plan['template_id']} v{plan['version']}":
        raise TemplateToolError("release plan release_name does not match template identity")
    expected_assets = [
        f"{plan['template_id']}-{plan['version']}.zip",
        f"{plan['template_id']}-{plan['version']}.zip.sha256",
        f"{plan['template_id']}-{plan['version']}.metadata.json",
    ]
    if [plan["archive"], plan["sha256"], plan["metadata"]] != expected_assets:
        raise TemplateToolError("release plan asset filenames do not match template identity")
    if not isinstance(plan["assets"], list) or len(plan["assets"]) != 3 or any(
        not isinstance(asset, str) for asset in plan["assets"]
    ):
        raise TemplateToolError("release plan assets must be a list of three filenames")
    if plan["assets"] != [plan["archive"], plan["sha256"], plan["metadata"]]:
        raise TemplateToolError("release plan assets must contain exactly the three bundle assets")
    for key in ("archive", "sha256", "metadata", "plan"):
        _strict_archive_name(plan[key], label=f"release plan.{key}")
        if Path(plan[key]).is_absolute():
            raise TemplateToolError("release plan may not contain absolute paths")
    _require_sha(plan["archive_sha256"], label="release plan.archive_sha256")
    if plan["prerelease"] is not False or plan["dry_run"] is not False:
        raise TemplateToolError("release plan prerelease and dry_run must be false")
    source_commit = plan["source_commit"]
    if not isinstance(source_commit, str) or len(source_commit) != 40 or not all(char in "0123456789abcdefABCDEF" for char in source_commit):
        raise TemplateToolError("release plan source_commit must be a full commit SHA")
    for asset in plan["assets"]:
        if Path(asset).name != asset:
            raise TemplateToolError("release plan assets must be plain filenames")
    if plan["plan"] != plan_path.name:
        raise TemplateToolError("release plan plan field does not match its filename")
    return plan


@dataclass(frozen=True)
class RemoteMasterIdentity:
    repository: GitHubRepositoryIdentity
    commit: str


def _assert_master_clean(
    root: Path,
    source_commit: str,
    repository: GitHubRepositoryIdentity,
) -> RemoteMasterIdentity:
    status = _run(["git", "status", "--porcelain"], root).stdout
    if status.strip():
        raise TemplateToolError("release publication requires a clean worktree")
    head = _run(["git", "rev-parse", "HEAD"], root).stdout.strip().lower()
    if head != source_commit.lower():
        raise TemplateToolError("release plan source_commit does not match current HEAD")
    remote = _run(
        ["git", "ls-remote", "--heads", "origin", "refs/heads/master"],
        root,
        check=False,
    )
    if remote.returncode != 0:
        details = remote.stderr.strip() or remote.stdout.strip()
        raise TemplateToolError(f"cannot confirm remote master: {details}")
    lines = [line.split() for line in remote.stdout.splitlines() if line.strip()]
    if len(lines) != 1 or len(lines[0]) != 2 or lines[0][1] != "refs/heads/master" or not re.fullmatch(
        r"[0-9a-fA-F]{40}", lines[0][0]
    ):
        raise TemplateToolError("cannot confirm a unique remote origin/master head")
    remote_head = lines[0][0].lower()
    if remote_head != head:
        raise TemplateToolError("release publication requires HEAD to equal the remote master head")
    branch = _run(["git", "branch", "--show-current"], root, check=False).stdout.strip()
    if branch != "master":
        raise TemplateToolError("release publication must run from master")
    return RemoteMasterIdentity(repository=repository, commit=remote_head)


@dataclass(frozen=True)
class _RemoteSnapshot:
    tag_exists: bool
    release_exists: bool
    assets: frozenset[str]


def _snapshot_remote(client: GitHubReleaseClient, tag: str) -> _RemoteSnapshot:
    tag_exists = client.tag_exists(tag)
    if tag_exists:
        client.tag_target(tag)
    release_exists = client.release_exists(tag)
    assets = frozenset(client.asset_names(tag)) if release_exists else frozenset()
    if release_exists:
        client.release_tag(tag)
    return _RemoteSnapshot(tag_exists=tag_exists, release_exists=release_exists, assets=assets)


def _reconcile_tag_ownership(
    client: GitHubReleaseClient,
    tag: str,
    source_commit: str,
    operation_id: str,
) -> bool:
    try:
        if not client.tag_exists(tag):
            return False
        identity = client.tag_annotation(tag)
    except Exception as exc:
        raise TemplateToolError(
            f"remote state changed but ownership could not be proven for tag {tag}: {exc}"
        ) from exc
    target = str(identity.get("target") or "")
    message = identity.get("message")
    if target.lower() != source_commit.lower() or not isinstance(message, str):
        raise TemplateToolError(
            f"remote tag was created concurrently by another publication: ownership could not be proven for {tag}"
        )
    operation_match = re.search(r"(?m)^Release operation: ([^\r\n]+)$", message)
    operation = operation_match.group(1) if operation_match else None
    if operation != operation_id:
        raise TemplateToolError(
            f"remote tag was created concurrently by another publication: operation identity mismatch for {tag}"
        )
    return True


def _reconcile_release_ownership(client: GitHubReleaseClient, tag: str, operation_id: str) -> bool:
    try:
        if not client.release_exists(tag):
            return False
        identity = client.release_identity(tag)
    except Exception as exc:
        raise TemplateToolError(
            f"remote state changed but ownership could not be proven for Release {tag}: {exc}"
        ) from exc
    body = identity.get("body")
    marker = f"<!-- template-release-operation:{operation_id} -->"
    if identity.get("tag") != tag or not isinstance(body, str) or marker not in body:
        raise TemplateToolError(
            f"remote Release was created concurrently by another publication: ownership could not be proven for {tag}"
        )
    return True


def _reconcile_asset_ownership(
    client: GitHubReleaseClient,
    tag: str,
    name: str,
    initial_assets: frozenset[str],
    operation_id: str,
    release_owned: bool,
) -> bool:
    try:
        if not release_owned:
            raise TemplateToolError("Release ownership was not proven")
        identity = client.release_identity(tag)
        body = identity.get("body")
        marker = f"<!-- template-release-operation:{operation_id} -->"
        if identity.get("tag") != tag or not isinstance(body, str) or marker not in body:
            raise TemplateToolError("Release operation identity mismatch")
        assets = client.asset_names(tag)
    except Exception as exc:
        raise TemplateToolError(
            f"remote state changed but ownership could not be proven for asset {name}: {exc}"
        ) from exc
    if name not in assets:
        return False
    if name in initial_assets:
        raise TemplateToolError(
            f"remote state changed but ownership could not be proven for asset {name}: pre-existing asset"
        )
    return True


def publish_release_transaction(
    plan_path: Path,
    root: Path,
    *,
    client: GitHubReleaseClient | None = None,
    body: str | None = None,
    repository: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    plan_path = plan_path.expanduser().absolute()
    plan = _validate_plan(plan_path, root)
    origin_repository = _assert_repository_identity(root, repository)
    _assert_master_clean(root, plan["source_commit"], origin_repository)
    assets = [plan_path.parent / name for name in plan["assets"]]
    for asset in assets:
        if asset.is_symlink() or not asset.is_file():
            raise TemplateToolError(f"release plan asset is missing: {asset.name}")
    archive_path = assets[0]
    sidecar_path = assets[1]
    metadata_path = assets[2]
    source_snapshot = release_source_snapshot_for_commit(
        root,
        template_id=plan["template_id"],
        version=plan["version"],
        format=plan["format"],
        source_commit=plan["source_commit"],
    )
    verification = verify_release_bundle(
        archive_path,
        root,
        sidecar_path=sidecar_path,
        metadata_path=metadata_path,
    )
    try:
        _verify_release_archive_matches_source_snapshot(
            archive_path,
            metadata_path,
            source_snapshot,
        )
    except TemplateToolError as exc:
        raise TemplateToolError(f"release bundle does not match source_commit: {exc}") from exc
    local_asset_hashes = {asset.name: sha256_file(asset) for asset in assets}
    if verification["archive_sha256"] != plan["archive_sha256"]:
        raise TemplateToolError("release plan archive SHA does not match the local bundle")
    if local_asset_hashes[plan["archive"]] != plan["archive_sha256"]:
        raise TemplateToolError("local archive SHA does not match the release plan")
    for key in ("template_id", "version", "format"):
        if verification[key] != plan[key]:
            raise TemplateToolError(f"release plan {key} does not match the verified bundle")
    if client is None:
        client = GhCliGitHubReleaseClient(root, repository=origin_repository.slug)
    elif isinstance(client, GhCliGitHubReleaseClient) and client.repository.casefold() != origin_repository.slug.casefold():
        raise TemplateToolError("GitHub repository client does not match origin")
    tag = plan["tag"]
    initial = _snapshot_remote(client, tag)
    if initial.tag_exists:
        raise TemplateToolError(f"release tag already exists: {tag}")
    if initial.release_exists:
        raise TemplateToolError(f"GitHub Release already exists: {tag}")
    operation_id = uuid.uuid4().hex
    tag_owned = False
    release_owned = False
    uploaded: list[str] = []
    ownership_unknown = False
    try:
        tag_message = (
            f"{plan['release_name']}\n\n"
            f"Source commit: {plan['source_commit']}\n"
            f"Release operation: {operation_id}"
        )
        try:
            client.create_tag(tag, plan["source_commit"], tag_message)
        except Exception as original:
            try:
                tag_owned = _reconcile_tag_ownership(client, tag, plan["source_commit"], operation_id)
            except Exception as reconciliation:
                ownership_unknown = True
                raise TemplateToolError(
                    f"{original}; ownership reconciliation error: {reconciliation}; manual cleanup may be required"
                ) from original
            raise
        try:
            tag_owned = _reconcile_tag_ownership(client, tag, plan["source_commit"], operation_id)
        except Exception:
            ownership_unknown = True
            raise
        if not tag_owned:
            raise TemplateToolError("created tag ownership could not be proven")

        release_body = body if body is not None else (
            f"Template: {plan['template_id']}\n"
            f"Version: {plan['version']}\n"
            f"Format: {plan['format']}\n"
            f"Archive SHA-256: {plan['archive_sha256']}\n"
            f"Source commit: {plan['source_commit']}\n\n"
            "Assets:\n"
            + "\n".join(f"- {name}" for name in plan["assets"])
            + "\n\nGitHub Actions does not run Microsoft Office COM or native Office rendering tests."
        )
        release_body = release_body.rstrip() + f"\n\n<!-- template-release-operation:{operation_id} -->"
        try:
            client.create_release(tag, plan["release_name"], release_body, bool(plan["prerelease"]))
        except Exception as original:
            try:
                release_owned = _reconcile_release_ownership(client, tag, operation_id)
            except Exception as reconciliation:
                ownership_unknown = True
                raise TemplateToolError(
                    f"{original}; ownership reconciliation error: {reconciliation}; manual cleanup may be required"
                ) from original
            raise
        try:
            release_owned = _reconcile_release_ownership(client, tag, operation_id)
        except Exception:
            ownership_unknown = True
            raise
        if not release_owned:
            raise TemplateToolError("created Release ownership could not be proven")

        for asset in assets:
            try:
                client.upload_asset(tag, asset)
            except Exception as original:
                try:
                    owned = _reconcile_asset_ownership(
                        client,
                        tag,
                        asset.name,
                        initial.assets,
                        operation_id,
                        release_owned,
                    )
                except Exception as reconciliation:
                    ownership_unknown = True
                    raise TemplateToolError(
                        f"{original}; ownership reconciliation error: {reconciliation}; manual cleanup may be required"
                    ) from original
                if owned:
                    uploaded.append(asset.name)
                raise
            try:
                owned = _reconcile_asset_ownership(
                    client,
                    tag,
                    asset.name,
                    initial.assets,
                    operation_id,
                    release_owned,
                )
            except Exception:
                ownership_unknown = True
                raise
            if not owned:
                raise TemplateToolError(f"created asset ownership could not be proven: {asset.name}")
            uploaded.append(asset.name)
        with tempfile.TemporaryDirectory(prefix="template-release-download-") as temporary_name:
            downloaded_dir = Path(temporary_name)
            downloaded: dict[str, Path] = {}
            for name in plan["assets"]:
                downloaded[name] = client.download_asset(tag, name, downloaded_dir / name)
            remote_asset_hashes = {name: sha256_file(path) for name, path in downloaded.items()}
            if remote_asset_hashes != local_asset_hashes:
                raise TemplateToolError(
                    "remote asset SHA does not match local release plan: "
                    f"local={local_asset_hashes}, remote={remote_asset_hashes}"
                )
            if remote_asset_hashes[plan["archive"]] != plan["archive_sha256"]:
                raise TemplateToolError("remote archive SHA does not match the release plan")
            downloaded_verification = verify_release_bundle(
                downloaded[plan["archive"]],
                root,
                sidecar_path=downloaded[plan["sha256"]],
                metadata_path=downloaded[plan["metadata"]],
            )
        return {
            "status": "passed",
            "template_id": plan["template_id"],
            "version": plan["version"],
            "tag": tag,
            "release_name": plan["release_name"],
            "assets": plan["assets"],
            "archive_sha256": downloaded_verification["archive_sha256"],
            "source_commit": plan["source_commit"],
            "operation_id": operation_id,
            "created_tag": tag_owned,
            "created_release": release_owned,
            "uploaded_assets": uploaded,
            "local_asset_sha256": local_asset_hashes,
            "remote_asset_sha256": remote_asset_hashes,
            "remote_assets_identical": True,
        }
    except Exception as original:
        cleanup_errors: list[str] = []
        if not ownership_unknown:
            for name in reversed(uploaded):
                try:
                    client.delete_asset(tag, name)
                except Exception as error:
                    cleanup_errors.append(f"failed to delete created asset {name}: {error}")
            if release_owned:
                try:
                    client.delete_release(tag)
                except Exception as error:
                    cleanup_errors.append(f"failed to delete created release: {error}")
            if tag_owned:
                try:
                    client.delete_tag(tag)
                except Exception as error:
                    cleanup_errors.append(f"failed to delete created tag: {error}")
        else:
            cleanup_errors.append("ownership is unknown; manual cleanup may be required")
        message = f"GitHub release transaction failed: {original}"
        if cleanup_errors:
            message += "; " + "; ".join(cleanup_errors)
        raise TemplateToolError(message) from original


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Publish a verified template package release to GitHub")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--body-file", type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        body = args.body_file.read_text(encoding="utf-8") if args.body_file else None
        result = publish_release_transaction(
            args.plan,
            args.repo_root,
            client=GhCliGitHubReleaseClient(args.repo_root, repository=args.repository),
            body=body,
            repository=args.repository,
        )
    except (TemplateToolError, OSError, ValueError) as exc:
        if args.json:
            print(json.dumps({"status": "failed", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result.get('status')}")
        print(f"tag: {result.get('tag')}")
        print(f"archive_sha256: {result.get('archive_sha256')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
