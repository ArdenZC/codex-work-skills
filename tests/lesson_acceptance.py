"""Test compatibility wrapper for the installed Lesson Acceptance runtime."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

_RUNTIME_PATH = SCRIPTS / "lesson_acceptance.py"
_SPEC = importlib.util.spec_from_file_location("lesson_acceptance_runtime", _RUNTIME_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Cannot load production Lesson Acceptance runtime: {_RUNTIME_PATH}")
_runtime = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_runtime)


def __getattr__(name: str):
    return getattr(_runtime, name)


def __dir__():
    return sorted(set(globals()) | set(dir(_runtime)))


if __name__ == "__main__":
    raise SystemExit(_runtime.main())