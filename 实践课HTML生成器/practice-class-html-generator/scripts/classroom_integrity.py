"""Classified classroom assets, project-bundle closure, and reference gates.

The module deliberately keeps the contract generic. A bundle is a manifest,
not a file generator: each file must either be backed by a starter asset, an
explicit source path, or inline content. The same materialisation code is
used for temporary verification roots and for the final student package.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from reference_behavior import control_flow, safe_path, verify_checks


STUDENT_ROLES = {"student-edit", "student-input", "runtime-required", "generated-scaffold"}
PRIVATE_ROLES = {"teacher-reference", "test-only"}
ALL_ROLES = STUDENT_ROLES | PRIVATE_ROLES
CLASSIFICATIONS = {
    "source-only-reference",
    "teacher-only-material",
    "student-classroom-input",
    "generated-starter-seed",
}
PUBLIC_CLASSIFICATIONS = {"student-classroom-input", "generated-starter-seed"}


def _normalise(value: Any) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bundle_root(bundle: dict[str, Any]) -> str:
    """Return a path relative to the starter root.

    Older examples used ``starter/foo`` while the contract says bundle roots
    are relative to ``student/starter``. Both forms are accepted.
    """

    raw = _normalise(bundle.get("root"))
    if raw.casefold() == "starter":
        return ""
    if raw.casefold().startswith("starter/"):
        raw = raw.split("/", 1)[1]
    return raw


def _bundle_file_path(bundle: dict[str, Any], item: dict[str, Any]) -> str:
    root = _bundle_root(bundle)
    relative = _normalise(item.get("path"))
    return "/".join(part for part in (root, relative) if part)


def _asset_index(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id")): item
        for item in content.get("starter_assets", [])
        if isinstance(item, dict) and item.get("id")
    }


def _bundle_asset(bundle: dict[str, Any], item: dict[str, Any], assets: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    explicit = item.get("asset_id")
    if explicit is not None and str(explicit) in assets:
        return assets[str(explicit)]
    bundle_path = _bundle_file_path(bundle, item)
    candidates = {
        _normalise(item.get("path")),
        bundle_path,
        f"starter/{bundle_path}" if bundle_path else "",
    }
    bundle_id = str(bundle.get("id", ""))
    for asset in assets.values():
        asset_path = _normalise(asset.get("path"))
        if asset_path in candidates:
            return asset
        if bundle_id and str(asset.get("bundle_id", "")) == bundle_id and asset_path.endswith("/" + _normalise(item.get("path"))):
            return asset
    return None


def _source_bytes(source_root: Path | None, source_path: str, expected_sha: str | None = None) -> bytes:
    if source_root is None:
        raise ValueError(f"source_root is required for source asset: {source_path}")
    source = safe_path(source_root, source_path)
    data = source.read_bytes()
    if expected_sha and _sha256_bytes(data) != str(expected_sha).lower():
        raise ValueError(f"source SHA mismatch: {source_path}")
    return data


def prepare_assets(content: dict[str, Any], source_root: Path | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Resolve classified raw assets into safe student starter entries."""

    result = copy.deepcopy(content)
    assets = result.setdefault("starter_assets", [])
    if not isinstance(assets, list):
        raise ValueError("starter_assets must be a list")
    lineage: list[dict[str, Any]] = []
    for item in result.get("classroom_assets", []):
        if not isinstance(item, dict):
            raise ValueError("classroom asset must be an object")
        classification = item.get("classification")
        if classification not in CLASSIFICATIONS:
            raise ValueError("classroom asset requires explicit classification")
        source_path = str(item.get("source_path", ""))
        if not source_path:
            raise ValueError("classroom asset source_path is required")
        source = safe_path(source_root, source_path)
        data = source.read_bytes()
        digest = _sha256_bytes(data)
        if str(item.get("sha256", "")).lower() != digest:
            raise ValueError("classroom asset source SHA mismatch: " + source_path)
        student_path = item.get("student_path")
        if classification in PUBLIC_CLASSIFICATIONS:
            if not isinstance(student_path, str) or not student_path.strip() or Path(student_path).is_absolute() or ".." in Path(student_path).parts:
                raise ValueError("student classroom asset needs a safe student_path: " + source_path)
            _safe_target(Path.cwd(), student_path)
            existing = next((a for a in assets if isinstance(a, dict) and a.get("id") == item.get("id")), None)
            public_asset = {
                "id": item.get("id"),
                "task_id": item.get("task_id"),
                "path": student_path,
                "title": item.get("title", item.get("id", "课堂输入")),
                "purpose": item.get("purpose", item.get("title", "课堂输入")),
                "language": item.get("language", "text"),
                "content": data.decode("utf-8-sig") if Path(source_path).suffix.casefold() in {".csv", ".txt", ".json", ".md", ".yaml", ".yml"} else "",
                "role": "student-input",
                "source_path": source_path,
                "source_sha256": digest,
            }
            if existing:
                if _normalise(existing.get("path")) != _normalise(student_path):
                    raise ValueError("classroom asset path conflicts with starter: " + str(item.get("id")))
                existing.update(public_asset)
            else:
                assets.append(public_asset)
            target = "student/starter/" + _normalise(student_path)
        else:
            target = None
        lineage.append(
            {
                "asset_id": item.get("id"),
                "source_path": source_path,
                "classification": classification,
                "decision": "student-distributable" if classification in PUBLIC_CLASSIFICATIONS else "teacher/source-only",
                "student_path": target,
                "source_sha256": digest,
                "student_sha256": digest if target else None,
            }
        )

    csv_inputs = any(str(a.get("path", "")).casefold().endswith(".csv") for a in assets if isinstance(a, dict))
    persistent_workbook = any(
        isinstance(task, dict)
        and task.get("artifact_kind") == "workbook"
        and set(task.get("capabilities", [])) & {"file_editing", "tool_operation", "visualization"}
        for task in result.get("tasks", [])
    )
    if csv_inputs and persistent_workbook and ".xlsx" not in str(result.get("spreadsheet_workflow", "")).casefold():
        raise ValueError("CSV input needs an explicit .xlsx working-copy workflow for persistent workbook editing")
    return result, lineage


def _safe_target(root: Path, relative: str) -> Path:
    return safe_path(root, relative)


def write_asset(asset: dict[str, Any], target: Path, source_root: Path | None = None, reference: bool = False) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if asset.get("source_path"):
        data = _source_bytes(source_root, str(asset["source_path"]), str(asset.get("source_sha256") or asset.get("sha256") or "") or None)
        target.write_bytes(data)
    else:
        target.write_text(str(asset.get("content", "")), encoding="utf-8", newline="\n")


def materialize_bundles(
    content: dict[str, Any],
    target_root: Path,
    source_root: Path | None = None,
    *,
    include_private: bool = False,
    reference_contents: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Materialise public or teacher bundle files under a starter root."""

    errors: list[str] = []
    files: list[str] = []
    assets = _asset_index(content)
    reference_contents = reference_contents or {}
    for bundle in content.get("starter_bundles", []):
        if not isinstance(bundle, dict):
            errors.append("starter bundle must be an object")
            continue
        try:
            _safe_target(target_root, _bundle_root(bundle) or ".")
        except (ValueError, TypeError) as exc:
            errors.append(f"bundle {bundle.get('id')}: unsafe root: {exc}")
            continue
        for item in bundle.get("files", []):
            if not isinstance(item, dict):
                errors.append(f"bundle {bundle.get('id')}: file must be an object")
                continue
            role = item.get("role")
            if role not in ALL_ROLES:
                errors.append(f"bundle {bundle.get('id')}: unknown role {role}")
                continue
            if role in PRIVATE_ROLES and not include_private:
                continue
            relative = _bundle_file_path(bundle, item)
            if not relative or not item.get("path"):
                errors.append(f"bundle {bundle.get('id')}: file path is required")
                continue
            try:
                target = _safe_target(target_root, relative)
            except (ValueError, TypeError) as exc:
                errors.append(f"bundle {bundle.get('id')}: unsafe file path: {exc}")
                continue
            asset = _bundle_asset(bundle, item, assets)
            try:
                if asset is not None and str(asset.get("id")) in reference_contents:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(reference_contents[str(asset["id"])], encoding="utf-8", newline="\n")
                elif asset is not None:
                    write_asset(asset, target, source_root, reference=include_private)
                elif item.get("source_path"):
                    data = _source_bytes(source_root, str(item["source_path"]), str(item.get("sha256", "")) or None)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                elif "content" in item:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    value = item.get("content")
                    if isinstance(value, str):
                        target.write_text(value, encoding="utf-8", newline="\n")
                    elif isinstance(value, (bytes, bytearray)):
                        target.write_bytes(bytes(value))
                    else:
                        target.write_text(str(value), encoding="utf-8", newline="\n")
                elif target.is_file():
                    pass
                else:
                    errors.append(f"bundle {bundle.get('id')}: no starter asset/source/content for {item.get('path')}")
                    continue
                files.append(relative)
            except (OSError, ValueError, UnicodeError) as exc:
                errors.append(f"bundle {bundle.get('id')} {item.get('path')}: {exc}")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "files": files}


def _literal_template_names(path: Path) -> tuple[list[str], bool]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return [], False
    names: list[str] = []
    dynamic = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name != "render_template":
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            names.append(node.args[0].value)
        else:
            dynamic = True
    return names, dynamic


def closure(content: dict[str, Any], root: Path) -> dict[str, Any]:
    """Check the student starter dependency closure without authoring files."""

    root = Path(root).resolve()
    errors: list[str] = []
    assets = _asset_index(content)
    paths: list[str] = []
    for asset in assets.values():
        path = _normalise(asset.get("path"))
        if not path:
            errors.append("starter asset path is empty")
            continue
        paths.append(path.casefold())
        role = asset.get("role", "student-edit")
        try:
            target = _safe_target(root, path)
        except (ValueError, TypeError) as exc:
            errors.append(f"unsafe starter asset path {path}: {exc}")
            continue
        if role not in ALL_ROLES:
            errors.append("unknown asset role: " + str(role))
        elif role in STUDENT_ROLES and not target.is_file():
            errors.append("missing runtime asset: " + path)
        elif role in PRIVATE_ROLES and target.exists():
            errors.append("teacher-only asset in student package: " + path)
    if len(paths) != len(set(paths)):
        errors.append("duplicate starter path")

    for task in content.get("tasks", []):
        if not isinstance(task, dict):
            continue
        for aid in task.get("starter_asset_ids", []):
            asset = assets.get(str(aid))
            if not asset or asset.get("role", "student-edit") not in STUDENT_ROLES:
                errors.append(f"task {task.get('id')} references non-student asset {aid}")
            elif not _safe_target(root, str(asset.get("path", ""))).is_file():
                errors.append(f"task {task.get('id')} missing student asset {aid}")

    for bundle in content.get("starter_bundles", []):
        if not isinstance(bundle, dict):
            errors.append("starter bundle must be an object")
            continue
        bundle_id = bundle.get("id")
        try:
            base = _safe_target(root, _bundle_root(bundle) or ".")
        except (ValueError, TypeError) as exc:
            errors.append(f"bundle {bundle_id}: unsafe root: {exc}")
            continue
        seen: set[str] = set()
        for item in bundle.get("files", []):
            if not isinstance(item, dict):
                errors.append(f"bundle {bundle_id}: file must be an object")
                continue
            role = item.get("role")
            relative = _normalise(item.get("path"))
            if role not in ALL_ROLES:
                errors.append(f"bundle {bundle_id}: unknown file role {role}")
            if not relative:
                errors.append(f"bundle {bundle_id}: file path is empty")
                continue
            if relative.casefold() in seen:
                errors.append(f"bundle {bundle_id}: duplicate file path {relative}")
            seen.add(relative.casefold())
            target = _safe_target(base, relative)
            if role in STUDENT_ROLES and not target.is_file():
                errors.append(f"missing bundle file: {target}")
            elif role in PRIVATE_ROLES and target.exists():
                errors.append("teacher-only bundle file leaked: " + str(target))
        entrypoint = bundle.get("entrypoint")
        if not isinstance(entrypoint, str) or not entrypoint.strip() or not _safe_target(base, entrypoint).is_file():
            errors.append(f"bundle {bundle_id}: bundle entrypoint missing")
        if str(bundle.get("framework", "")).casefold() == "flask":
            template_root = _normalise(bundle.get("template_path", "templates"))
            for source in base.rglob("*.py") if base.exists() else []:
                names, dynamic = _literal_template_names(source)
                if dynamic and not bundle.get("dynamic_template_assets"):
                    errors.append(f"bundle {bundle_id}: dynamic template requires explicit dynamic_template_assets")
                for name in names:
                    template = _safe_target(base, f"{template_root}/{name}")
                    if not template.is_file():
                        errors.append(f"missing template: {template}")
            for name in bundle.get("dynamic_template_assets", []):
                if not _safe_target(base, name).is_file():
                    errors.append(f"dynamic template missing: {name}")
        for source in base.rglob("*") if base.exists() else []:
            if not source.is_file() or source.suffix.casefold() not in {".html", ".htm"}:
                continue
            try:
                text = source.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                continue
            for reference in re.findall(r"(?:href|src)\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.I):
                if reference.startswith(("#", "/", "http:", "https:", "data:", "mailto:")):
                    continue
                target = (source.parent / reference.split("#", 1)[0].split("?", 1)[0]).resolve()
                try:
                    target.relative_to(base.resolve())
                except ValueError:
                    errors.append(f"bundle {bundle_id}: link escapes bundle: {reference}")
                else:
                    if not target.is_file():
                        errors.append(f"bundle {bundle_id}: missing linked asset: {reference}")

    for item in content.get("classroom_assets", []):
        if not isinstance(item, dict):
            errors.append("classroom asset must be an object")
            continue
        classification = item.get("classification")
        if classification not in CLASSIFICATIONS:
            errors.append("unknown classroom asset classification: " + str(classification))
        if classification in PUBLIC_CLASSIFICATIONS:
            student_path = item.get("student_path")
            try:
                target = _safe_target(root, str(student_path or ""))
            except (ValueError, TypeError) as exc:
                errors.append(f"unsafe classroom student_path: {exc}")
                continue
            if not target.is_file() or _sha256_bytes(target.read_bytes()) != str(item.get("sha256", "")).lower():
                errors.append("classroom passthrough missing or hash mismatch: " + str(item.get("source_path")))

    for dep in content.get("runtime_dependencies", []):
        path = dep.get("path") if isinstance(dep, dict) else dep
        try:
            if not _safe_target(root, str(path or "")).is_file():
                errors.append("missing declared runtime dependency: " + str(path))
        except (ValueError, TypeError) as exc:
            errors.append(f"unsafe declared runtime dependency {path}: {exc}")
    return {"status": "PASS" if not errors else "FAIL", "gate": "CLASSROOM_PACKAGE_INTEGRITY", "errors": errors}


def _task_requires_behavior(task: dict[str, Any]) -> bool:
    capabilities = set(task.get("required_capabilities", task.get("capabilities", [])))
    kind = task.get("task_kind", task.get("type"))
    return kind in {"implementation", "debugging", "code_editing", "execution"} or bool(capabilities & {"implementation", "debugging", "code_editing", "execution"})


def _qualify_check_paths(content: dict[str, Any], task: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    qualified = copy.deepcopy(verification)
    bundles = {str(item.get("id")): item for item in content.get("starter_bundles", []) if isinstance(item, dict) and item.get("id")}
    bundle_id = task.get("starter_bundle_id")
    if not bundle_id:
        ids = task.get("starter_bundle_ids", [])
        bundle_id = ids[0] if isinstance(ids, list) and len(ids) == 1 else None
    if bundle_id is None and len(bundles) == 1:
        bundle_id = next(iter(bundles))
    bundle = bundles.get(str(bundle_id)) if bundle_id is not None else None
    if not bundle:
        return qualified
    root = _bundle_root(bundle)
    for check in qualified.get("checks", []):
        if not isinstance(check, dict) or not check.get("entrypoint") or not root:
            continue
        entrypoint = _normalise(check["entrypoint"])
        if not entrypoint.casefold().startswith(root.casefold() + "/"):
            check["entrypoint"] = f"{root}/{entrypoint}"
    return qualified


def reference_gate(content: dict[str, Any], source_root: Path | None = None, output_dir: Path | None = None) -> dict[str, Any]:
    """Build a completed teacher root and require executable evidence."""

    errors: list[str] = []
    warnings: list[str] = []
    tasks: list[dict[str, Any]] = []
    completed: dict[str, dict[str, Any]] = {}
    bundle_report: dict[str, Any] = {"status": "PASS", "errors": [], "files": []}
    package: dict[str, Any] = {"status": "FAIL", "gate": "CLASSROOM_PACKAGE_INTEGRITY", "errors": ["reference root not built"]}
    with tempfile.TemporaryDirectory(prefix="classroom-reference-") as tmp:
        student, teacher = Path(tmp) / "student", Path(tmp) / "teacher"
        student.mkdir()
        teacher.mkdir()
        for asset in content.get("starter_assets", []):
            if not isinstance(asset, dict):
                continue
            role = asset.get("role", "student-edit")
            try:
                if role in STUDENT_ROLES:
                    write_asset(asset, _safe_target(student, asset.get("path", "")), source_root)
                if role in ALL_ROLES:
                    write_asset(asset, _safe_target(teacher, asset.get("path", "")), source_root)
                completed[str(asset.get("id"))] = {"path": asset.get("path"), "content": str(asset.get("content", ""))}
            except (OSError, ValueError, UnicodeError) as exc:
                errors.append(f"starter asset {asset.get('id')}: {exc}")
            try:
                from apply_reference_gaps import apply_asset_gaps

                reference_content, apply_errors = apply_asset_gaps(asset)
                errors.extend(f"{asset.get('id')}: {item}" for item in apply_errors)
                if not apply_errors:
                    if role in ALL_ROLES:
                        ref_asset = dict(asset, content=reference_content, source_path=None, source_sha256=None)
                        write_asset(ref_asset, _safe_target(teacher, asset.get("path", "")), source_root)
                    completed[str(asset.get("id"))] = {"path": asset.get("path"), "content": reference_content}
                    if Path(str(asset.get("path", ""))).suffix.casefold() == ".py":
                        try:
                            warnings.extend(control_flow(reference_content))
                        except SyntaxError as exc:
                            errors.append(str(exc))
            except Exception as exc:  # pragma: no cover - contract boundary
                errors.append(f"{asset.get('id')}: reference build failed: {exc}")

        reference_contents = {key: value["content"] for key, value in completed.items()}
        student_bundle_report = materialize_bundles(content, student, source_root, include_private=False)
        errors.extend(student_bundle_report["errors"])
        bundle_report = materialize_bundles(content, teacher, source_root, include_private=True, reference_contents=reference_contents)
        errors.extend(bundle_report["errors"])
        package = closure(content, student)
        errors.extend(package["errors"])
        refs = {
            str(item.get("task_id")): item
            for item in content.get("teacher_reference", {}).get("task_references", [])
            if isinstance(item, dict) and item.get("task_id")
        }
        for task in content.get("tasks", []):
            if not isinstance(task, dict) or not task.get("id"):
                continue
            verification = task.get("reference_verification")
            required = _task_requires_behavior(task)
            if required and not verification:
                errors.append("REFERENCE_BEHAVIOR_FAIL: missing verification for " + str(task["id"]))
                continue
            if not verification:
                continue
            qualified = _qualify_check_paths(content, task, verification)
            if required and str(content.get("course_context", {}).get("framework", "")).casefold() == "flask":
                if not content.get("starter_bundles"):
                    errors.append("Flask execution requires a project starter bundle")
                web_checks = [c for c in qualified.get("checks", []) if isinstance(c, dict) and c.get("verification_type") == "web-request"]
                scenarios = {
                    (c.get("method", "GET"), c.get("path"), repr(c.get("query_string")), repr(c.get("data")), repr(c.get("json")))
                    for c in web_checks
                }
                if len(web_checks) < 2 or len(scenarios) < 2:
                    errors.append("web behavior needs distinct input scenarios, not syntax alone")
            report = verify_checks(teacher, qualified)
            report["task_id"] = task["id"]
            report["required"] = required
            tasks.append(report)
            if report["status"] == "REFERENCE_BEHAVIOR_FAIL":
                errors.append("REFERENCE_BEHAVIOR_FAIL: " + str(task["id"]))
            ref = refs.get(str(task["id"]))
            if ref is not None:
                ref["verified_reference"] = [completed[x] for x in task.get("starter_asset_ids", []) if str(x) in completed]
                ref["behavior_evidence"] = report
            elif required:
                errors.append("teacher reference is missing for executable task: " + str(task["id"]))
        if output_dir is not None and not errors:
            target = Path(output_dir)
            target.mkdir(parents=True, exist_ok=True)
            shutil.copytree(teacher, target / "reference", dirs_exist_ok=True)
    return {
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "warnings": warnings,
        "tasks": tasks,
        "package_closure": package,
        "bundle_materialization": bundle_report,
        "control_flow": warnings,
    }


def package_links(root: Path) -> dict[str, Any]:
    from urllib.parse import unquote, urlsplit

    errors: list[str] = []
    root = Path(root).resolve()
    for page in root.rglob("*.html"):
        try:
            text = page.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"cannot read student page {page}: {exc}")
            continue
        for link in re.findall(r"(?:href|src)=[\'\"]([^\'\"]+)[\'\"]", text, flags=re.I):
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target = (page.parent / unquote(parsed.path)).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                errors.append("student link escapes package: " + link)
                continue
            if not target.is_file():
                errors.append("unresolved student link: " + link)
    return {"status": "FAIL" if errors else "PASS", "errors": errors}
