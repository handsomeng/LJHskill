#!/usr/bin/env python3
"""LJHskill 调用后更新提醒。零第三方依赖，异常静默降级。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen


LOCAL_VERSION = "1.0.0"
RELEASE_URL = "https://raw.githubusercontent.com/handsomeng/LJHskill/main/release.json"
DEFAULT_STATE_PATH = Path.home() / ".cache" / "ljhskill" / "update-check.json"
CHECK_INTERVAL = timedelta(hours=48)
REMINDER_INTERVAL = timedelta(days=7)
TIMEOUT_SECONDS = 3
MAX_RELEASE_BYTES = 256 * 1024
SEMVER_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def _env_value(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (TypeError, ValueError, OverflowError):
        return None


def _current_time(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return _as_utc(value)
    parsed = _parse_timestamp(value)
    return parsed or datetime.now(timezone.utc)


def _normalize_version(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized.startswith("v"):
        normalized = normalized[1:]
    return normalized or None


def _version_key(value: object) -> tuple[int, int, int] | None:
    normalized = _normalize_version(value)
    if normalized is None:
        return None
    match = SEMVER_PATTERN.fullmatch(normalized)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _read_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeError, TypeError, ValueError):
        return {}


def _write_state(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeError, TypeError, ValueError):
        pass


def _read_release(release_file: str | Path | None) -> dict:
    if release_file:
        raw = Path(release_file).read_bytes()
    else:
        request = Request(
            RELEASE_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "LJHskill-update-check/1.0.0",
            },
            method="GET",
        )
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RELEASE_BYTES + 1)

    if len(raw) > MAX_RELEASE_BYTES:
        raise ValueError("release.json 过大")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("release.json 顶层必须是对象")
    return data


def _resolve_path(value: str | Path | None, default: Path) -> Path:
    return Path(value).expanduser() if value else default


def check_for_update(
    release_file: str | Path | None = None,
    state_path: str | Path | None = None,
    now: datetime | str | None = None,
    local_version: str = LOCAL_VERSION,
) -> str:
    """检查新版本，返回一条提醒文本或空字符串。"""
    if os.environ.get("LJHSKILL_DISABLE_UPDATE_CHECK") == "1":
        return ""

    current = _current_time(now)
    state_file = _resolve_path(state_path, DEFAULT_STATE_PATH)
    state = _read_state(state_file)
    last_checked_at = _parse_timestamp(state.get("last_checked_at"))
    if last_checked_at is not None and current - last_checked_at < CHECK_INTERVAL:
        return ""

    state["last_checked_at"] = current.isoformat()
    try:
        release = _read_release(release_file)
        remote_version = _normalize_version(
            release.get("version", release.get("suite_version"))
        )
        local_display_version = _normalize_version(local_version)
        remote_key = _version_key(remote_version)
        local_key = _version_key(local_display_version)
        if remote_key is None or local_key is None:
            raise ValueError("版本格式无效")
    except Exception:
        _write_state(state_file, state)
        return ""

    state["last_success_at"] = current.isoformat()
    message = ""
    if remote_key > local_key:
        notified_version = _normalize_version(state.get("last_notified_version"))
        notified_at = _parse_timestamp(state.get("last_notified_at"))
        should_notify = notified_version != remote_version
        if not should_notify and notified_at is not None:
            should_notify = current - notified_at >= REMINDER_INTERVAL
        elif not should_notify:
            should_notify = True

        if should_notify:
            summary = release.get("summary")
            update_url = (
                release.get("update_instructions_url")
                or release.get("readme_url")
                or release.get("readme_update_entry")
            )
            details = []
            if isinstance(summary, str) and summary.strip():
                details.append(summary.strip())
            if isinstance(update_url, str) and update_url.strip():
                details.append(f"请按说明更新：{update_url.strip()}")
            suffix = " ".join(details)
            message = (
                f"更新提示：LJHskill 有新版本 v{remote_version}，"
                f"当前版本 v{local_display_version}。{suffix}"
            ).rstrip()
            state["last_notified_version"] = remote_version
            state["last_notified_at"] = current.isoformat()

    _write_state(state_file, state)
    return message


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LJHskill 更新提醒")
    parser.add_argument("--release-file", help="仅供测试使用的本地 release.json")
    parser.add_argument("--state-file", help="仅供测试使用的状态文件")
    parser.add_argument("--now", help="仅供测试使用的 ISO 8601 当前时间")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    release_file = args.release_file or _env_value(
        "LJHSKILL_UPDATE_RELEASE_FILE",
        "LJHSKILL_UPDATE_CHECK_RELEASE_FILE",
    )
    state_path = args.state_file or _env_value(
        "LJHSKILL_UPDATE_STATE_FILE",
        "LJHSKILL_UPDATE_CHECK_STATE_FILE",
    )
    now = args.now or _env_value("LJHSKILL_UPDATE_NOW", "LJHSKILL_UPDATE_CHECK_NOW")
    message = check_for_update(release_file=release_file, state_path=state_path, now=now)
    if message:
        print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
