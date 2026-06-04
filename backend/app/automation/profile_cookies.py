"""Portable session cookies (Windows login → Linux Docker Chromium)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

COOKIES_FILENAME = ".velora_cookies.json"
STORAGE_STATE_FILENAME = ".velora_storage_state.json"


def cookies_file(profile_dir: Path) -> Path:
    return profile_dir / COOKIES_FILENAME


def save_portable_cookies(profile_dir: Path, cookies: list[dict[str, Any]]) -> Path:
    path = cookies_file(profile_dir)
    path.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")
    return path


def load_portable_cookies(profile_dir: Path) -> list[dict[str, Any]]:
    path = cookies_file(profile_dir)
    if not path.is_file() or path.stat().st_size < 2:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [c for c in data if isinstance(c, dict) and c.get("name") and (c.get("domain") or c.get("url"))]


def storage_state_file(profile_dir: Path) -> Path:
    return profile_dir / STORAGE_STATE_FILENAME


def load_portable_storage_state(profile_dir: Path) -> dict[str, Any]:
    path = storage_state_file(profile_dir)
    if not path.is_file() or path.stat().st_size < 2:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
