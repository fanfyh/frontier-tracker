#!/usr/bin/env python3
"""Preflight check for Frontier Tracker — validates configuration WITHOUT making
any real API calls or spending quota.

Verifies:
  - Required / optional API keys are present (read from .env via _bootstrap, then
    real environment).
  - Python dependencies are importable (pyalex, openai).
  - Runtime files/paths exist and are writable (state, profile, watchlist,
    outputs/data, vault Orient dir).

Exit code: 0 if every REQUIRED check passes; 1 if any required check fails.
Optional checks (Elsevier) never cause a non-zero exit — they only warn.

Usage:
    python scripts/check_config.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  — loads .env so keys are visible below

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "state" / "reading_state.json"
PROFILE_FILE = ROOT / "references" / "fanfy-housing-fiscal.md"
WATCHLIST_FILE = ROOT / "references" / "top-journal-families.md"
OUTPUTS_DIR = ROOT / "outputs" / "data"
VAULT_ROOT = Path(os.environ.get("FRONTIER_TRACKER_VAULT_ROOT", str(Path.home() / "Documents" / "marginal-notes")))
ORIENT_DIR = VAULT_ROOT / "01_Research" / "01_Orient"


def _ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def _warn(msg: str) -> None:
    print(f"  \033[33m!\033[0m {msg} (optional)")


def _fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}")


def _writable(p: Path) -> bool:
    try:
        # Touch-create if missing; if it exists, probe write access.
        if p.exists():
            return os.access(p, os.W_OK)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
        p.unlink()
        return True
    except OSError:
        return False


def _importable(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def main() -> int:
    failures = 0

    print("\n=== API keys (from .env or environment) ===")
    if os.environ.get("OPENALEX_API_KEY"):
        _ok("OPENALEX_API_KEY set (scan + enrich)")
    else:
        _fail("OPENALEX_API_KEY missing — required by scan_recent_papers.py / enrich_abstracts.py. Put it in .env")
        failures += 1

    if os.environ.get("DEEPSEEK_API_KEY"):
        _ok("DEEPSEEK_API_KEY set (LLM judge)")
    else:
        _fail("DEEPSEEK_API_KEY missing — required by enrich_and_judge.py. Put it in .env")
        failures += 1

    if os.environ.get("ELSEVIER_API_KEY") and os.environ.get("ELSEVIER_INSTTOKEN"):
        _ok("ELSEVIER_API_KEY + ELSEVIER_INSTTOKEN set (fresh Elsevier abstracts)")
    elif os.environ.get("ELSEVIER_API_KEY") and not os.environ.get("ELSEVIER_INSTTOKEN"):
        _warn("ELSEVIER_API_KEY set but ELSEVIER_INSTTOKEN missing — a bare key only returns titles")
    else:
        _warn("ELSEVIER keys not set — fresh Elsevier abstracts (JUE/JPubE/JHE/...) will be skipped")

    print("\n=== Python dependencies ===")
    if _importable("pyalex"):
        _ok("pyalex importable (enrich_abstracts.py)")
    else:
        _fail("pyalex NOT installed — run: pip3 install pyalex")
        failures += 1
    if _importable("openai"):
        _ok("openai importable (enrich_and_judge.py)")
    else:
        _fail("openai NOT installed — run: pip3 install openai")
        failures += 1
    if _importable("dotenv"):
        _ok("python-dotenv importable (.env loader)")
    else:
        _warn("python-dotenv NOT installed — .env won't auto-load (run: pip3 install python-dotenv)")

    print("\n=== Runtime paths ===")
    for label, path, must_exist, writable in (
        ("state file", STATE_FILE, True, True),
        ("research profile", PROFILE_FILE, True, False),
        ("watchlist reference", WATCHLIST_FILE, True, False),
        ("outputs/data", OUTPUTS_DIR, True, True),
        ("vault Orient dir", ORIENT_DIR, True, True),
    ):
        if path.exists():
            detail = "" if not writable else (" (writable)" if os.access(path, os.W_OK) else " (NOT writable)")
            _ok(f"{label}: {path}{detail}")
            if writable and not os.access(path, os.W_OK):
                failures += 1
        else:
            level = _fail if must_exist else _warn
            level(f"{label} not found: {path}")
            if must_exist:
                failures += 1

    print("\n=== Result ===")
    if failures == 0:
        print("  \033[32mALL REQUIRED CHECKS PASSED — safe to run the pipeline.\033[0m\n")
        return 0
    print(f"  \033[31m{failures} required check(s) FAILED — fix before running.\033[0m\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
