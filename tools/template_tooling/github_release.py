"""GitHub Release adapter with a fail-closed, fake-testable transaction."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .manifest import sha256_file
from .models import RELEASE_TOOL_VERSION, TemplateToolError, parse_semver
from .paths import atomic_write_text, remove_path_or_raise, validate_windows_component
from .release import (
    RELEASE_PLAN_SCHEMA_VERSION,
    _load_json_object,
    _require_sha,
    _strict_archive_name,
    verify_release_bundle,
)


class GitHubReleaseClient(Protocol):
    """The small remote surface required by the publication transaction."""

    def tag_exists(self, tag: str) -> bool: ...

    def tag_target(self, tag: str) -> str: ...

    def release_exists(self, tag: str) -> bool: ...

    def release_tag(self, tag: str) -> str: ...

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
        self.repository = repository

    def _gh(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        command = ["gh", *arguments]
        if self.repository:
            command.extend(["--repo", self.repository])
        return _run(command, self.root, check=check)

    def tag_exists(self, tag: str) -> bool:
        result = _run(["git", "ls-remote", "--exit-code", "origin", f"refs/tags/{tag}"], self.root, check=False)
        if result.returncode == 0:
            return True
        if result.returncode == 2:
            return False
        details = result.stderr.strip() or result.stdout.strip()
        raise TemplateToolError(f"cannot check remote tag {tag}: {details}")

    def tag_target(self, tag: str) -> str:
        result = _run(
            ["git", "ls-remote", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
            self.root,
        )
        direct: str | None = None
        dereferenced: str | None = None
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) != 2 or not re.fullmatch(r"[0-9a-fA-F]{40}", fields[0]):
                continue
            if fields[1] == f"refs/tags/{tag}^{{}}":
                dereferenced = fields[0]
            elif fields[1] == f"refs/tags/{tag}":
                direct = fields[0]
        target = dereferenced or direct
        if target is None:
            raise TemplateToolError(f"remote tag target could not be resolved: {tag}")
        return target.lower()

    def release_exists(self, tag: str) -> bool:
        result = self._gh("release", "view", tag, check=False)
        if result.returncode == 0:
            return True
        details = f"{result.stderr}\n{result.stdout}".strip()
        if re.search(r"(?:not found|404)", details, re.IGNORECASE):
            return False
        raise TemplateToolError(f"cannot check GitHub Release {tag}: {details}")

    def release_tag(self, tag: str) -> str:
        result = self._gh("release", "view", tag, "--json", "tagName")
        try:
            value = json.loads(result.stdout)["tagName"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise TemplateToolError("gh release view returned invalid tag JSON") from exc
        if not isinstance(value, str) or not value:
            raise TemplateToolError("GitHub Release returned an empty tag name")
        return value

    def asset_names(self, tag: str) -> set[str]:
        result = self._gh("release", "view", tag, "--json", "assets", check=True)
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
            self._gh(*arguments)
        finally:
            if notes_file.exists() or notes_file.is_symlink():
                remove_path_or_raise(notes_file)

    def delete_release(self, tag: str) -> None:
        self._gh("release", "delete", tag, "--yes")

    def upload_asset(self, tag: str, path: Path) -> None:
        # No --clobber: a pre-existing or concurrently-created asset fails closed.
        self._gh("release", "upload", tag, str(path))

    def delete_asset(self, tag: str, name: str) -> None:
        self._gh("release", "delete-asset", tag, name, "--yes")

    def download_asset(self, tag: str, name: str, destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=False)
        self._gh("release", "download", tag, "--pattern", name, "--dir", str(destination))
        path = destination / name
        if not path.is_file() or path.is_symlink():
            raise TemplateToolError(f"downloaded release asset is missing: {name}")
        return path


class InMemoryGitHubReleaseClient:
    """Fake adapter for transaction rehearsals and deterministic unit tests."""

    def __init__(self, *, fail_at: str | set[str] | None = None) -> None:
        self.tags: dict[str, str] = {}
        self.releases: dict[str, dict[str, Any]] = {}
        self.fail_at = fail_at
        self.events: list[str] = []

    def _fail(self, event: str) -> None:
        self.events.append(event)
        if event == self.fail_at or (isinstance(self.fail_at, set) and event in self.fail_at):
            raise TemplateToolError(f"injected GitHub adapter failure: {event}")

    def _mutate_then_raise(self, event: str) -> None:
        marker = f"mutate_then_raise:{event}"
        if marker == self.fail_at or (isinstance(self.fail_at, set) and marker in self.fail_at):
            raise TemplateToolError(f"injected GitHub adapter failure after mutation: {event}")

    def tag_exists(self, tag: str) -> bool:
        return tag in self.tags

    def tag_target(self, tag: str) -> str:
        if tag not in self.tags:
            raise TemplateToolError(f"fake tag does not exist: {tag}")
        return self.tags[tag].lower()

    def release_exists(self, tag: str) -> bool:
        return tag in self.releases

    def release_tag(self, tag: str) -> str:
        if tag not in self.releases:
            raise TemplateToolError(f"fake release does not exist: {tag}")
        return tag

    def asset_names(self, tag: str) -> set[str]:
        return set(self.releases.get(tag, {}).get("assets", {}))

    def create_tag(self, tag: str, source_commit: str, message: str) -> None:
        self._fail("create_tag")
        self.tags[tag] = source_commit
        self._mutate_then_raise("create_tag")

    def delete_tag(self, tag: str) -> None:
        self._fail("delete_tag")
        self.tags.pop(tag, None)

    def create_release(self, tag: str, name: str, body: str, prerelease: bool) -> None:
        self._fail("create_release")
        self.releases[tag] = {"name": name, "body": body, "prerelease": prerelease, "assets": {}}
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


def _assert_master_clean(root: Path, source_commit: str) -> None:
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


def _reconcile_tag_ownership(client: GitHubReleaseClient, tag: str, source_commit: str) -> bool:
    try:
        if not client.tag_exists(tag):
            return False
        target = client.tag_target(tag)
    except Exception as exc:
        raise TemplateToolError(
            f"remote state changed but ownership could not be proven for tag {tag}: {exc}"
        ) from exc
    if target.lower() != source_commit.lower():
        raise TemplateToolError(
            f"remote state changed but ownership could not be proven for tag {tag}: target mismatch"
        )
    return True


def _reconcile_release_ownership(client: GitHubReleaseClient, tag: str) -> bool:
    try:
        if not client.release_exists(tag):
            return False
        release_tag = client.release_tag(tag)
    except Exception as exc:
        raise TemplateToolError(
            f"remote state changed but ownership could not be proven for Release {tag}: {exc}"
        ) from exc
    if release_tag != tag:
        raise TemplateToolError(
            f"remote state changed but ownership could not be proven for Release {tag}: tag mismatch"
        )
    return True


def _reconcile_asset_ownership(
    client: GitHubReleaseClient,
    tag: str,
    name: str,
    initial_assets: frozenset[str],
) -> bool:
    try:
        if client.release_tag(tag) != tag:
            raise TemplateToolError("Release tag mismatch")
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
) -> dict[str, Any]:
    root = root.resolve()
    plan_path = plan_path.expanduser().absolute()
    plan = _validate_plan(plan_path, root)
    _assert_master_clean(root, plan["source_commit"])
    assets = [plan_path.parent / name for name in plan["assets"]]
    for asset in assets:
        if asset.is_symlink() or not asset.is_file():
            raise TemplateToolError(f"release plan asset is missing: {asset.name}")
    archive_path = assets[0]
    sidecar_path = assets[1]
    metadata_path = assets[2]
    verification = verify_release_bundle(
        archive_path,
        root,
        sidecar_path=sidecar_path,
        metadata_path=metadata_path,
    )
    local_asset_hashes = {asset.name: sha256_file(asset) for asset in assets}
    if verification["archive_sha256"] != plan["archive_sha256"]:
        raise TemplateToolError("release plan archive SHA does not match the local bundle")
    if local_asset_hashes[plan["archive"]] != plan["archive_sha256"]:
        raise TemplateToolError("local archive SHA does not match the release plan")
    for key in ("template_id", "version", "format"):
        if verification[key] != plan[key]:
            raise TemplateToolError(f"release plan {key} does not match the verified bundle")
    client = client or GhCliGitHubReleaseClient(root)
    tag = plan["tag"]
    initial = _snapshot_remote(client, tag)
    if initial.tag_exists:
        raise TemplateToolError(f"release tag already exists: {tag}")
    if initial.release_exists:
        raise TemplateToolError(f"GitHub Release already exists: {tag}")
    created_tag = False
    created_release = False
    uploaded: list[str] = []
    try:
        try:
            client.create_tag(tag, plan["source_commit"], f"{plan['release_name']}\n\n{plan['source_commit']}")
            if client.tag_target(tag) != plan["source_commit"].lower():
                raise TemplateToolError("created tag target does not match release plan source_commit")
            created_tag = True
        except Exception as original:
            if _reconcile_tag_ownership(client, tag, plan["source_commit"]):
                created_tag = True
            raise original
        release_body = body or (
            f"Template: {plan['template_id']}\n"
            f"Version: {plan['version']}\n"
            f"Format: {plan['format']}\n"
            f"Archive SHA-256: {plan['archive_sha256']}\n"
            f"Source commit: {plan['source_commit']}\n\n"
            "Assets:\n"
            + "\n".join(f"- {name}" for name in plan["assets"])
            + "\n\nGitHub Actions does not run Microsoft Office COM or native Office rendering tests."
        )
        try:
            client.create_release(tag, plan["release_name"], release_body, bool(plan["prerelease"]))
            if client.release_tag(tag) != tag:
                raise TemplateToolError("created GitHub Release tag does not match the release plan")
            created_release = True
        except Exception as original:
            if _reconcile_release_ownership(client, tag):
                created_release = True
            raise original
        for asset in assets:
            try:
                client.upload_asset(tag, asset)
                uploaded.append(asset.name)
            except Exception as original:
                if _reconcile_asset_ownership(client, tag, asset.name, initial.assets):
                    uploaded.append(asset.name)
                raise original
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
            "created_tag": created_tag,
            "created_release": created_release,
            "uploaded_assets": uploaded,
            "local_asset_sha256": local_asset_hashes,
            "remote_asset_sha256": remote_asset_hashes,
            "remote_assets_identical": True,
        }
    except Exception as original:
        cleanup_errors: list[str] = []
        for name in reversed(uploaded):
            try:
                client.delete_asset(tag, name)
            except Exception as error:
                cleanup_errors.append(f"failed to delete created asset {name}: {error}")
        if created_release:
            try:
                client.delete_release(tag)
            except Exception as error:
                cleanup_errors.append(f"failed to delete created release: {error}")
        if created_tag:
            try:
                client.delete_tag(tag)
            except Exception as error:
                cleanup_errors.append(f"failed to delete created tag: {error}")
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
