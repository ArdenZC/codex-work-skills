"""Shared deterministic helpers for the whole-course orchestration layer."""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class OrchestrationError(ValueError):
    """Raised when a course-level contract cannot be accepted."""


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def dump_json(value: Any, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def safe_filename(value: str, *, fallback: str = "item", max_length: int = 120) -> str:
    """Turn a display title into a portable filename without path traversal."""

    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    text = text or fallback
    if text in {".", ".."}:
        text = fallback
    return text[:max_length].rstrip(" .") or fallback


def slug(value: str, *, fallback: str = "item") -> str:
    text = safe_filename(value, fallback=fallback).lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text).strip("-")
    return text or fallback


def text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(text_of(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return " ".join(text_of(item) for item in value)
    return str(value)


def tokenise(value: Any) -> list[str]:
    """Tokenise English words and CJK characters for stable similarity checks."""

    text = unicodedata.normalize("NFKC", text_of(value)).lower()
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text)
    return [word for word in words if word not in {"the", "a", "an", "and", "or", "to", "of"}]


def ngrams(value: Any, size: int = 3) -> set[tuple[str, ...]]:
    tokens = tokenise(value)
    if len(tokens) < size:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def jaccard(left: Iterable[Any], right: Iterable[Any]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def nested_values(value: Any) -> Iterable[Any]:
    if isinstance(value, Mapping):
        for item in value.values():
            yield item
            yield from nested_values(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield item
            yield from nested_values(item)


def contains_any(value: Any, needles: Iterable[str]) -> bool:
    haystack = text_of(value).lower()
    return any(str(needle).lower() in haystack for needle in needles)


def relative_posix(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def html_page(title: str, body: str) -> str:
    safe_title = html.escape(title)
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{safe_title}</title>"
        "<style>body{font-family:system-ui,'Microsoft YaHei',sans-serif;margin:2rem;color:#243447;line-height:1.6}"
        "main{max-width:1100px;margin:auto}table{border-collapse:collapse;width:100%;margin:1rem 0}"
        "th,td{border:1px solid #c9d5e2;padding:.5rem;text-align:left;vertical-align:top}"
        "th{background:#eef4f8}code{background:#f3f5f7;padding:.1rem .25rem;border-radius:3px}"
        ".warning{color:#8a4b08}.fail{color:#a32929}.ok{color:#1d6b45}"
        "</style></head><body><main>" + body + "</main></body></html>"
    )
