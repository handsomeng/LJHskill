#!/usr/bin/env python3
"""Apify 客户端：抖音作品数据、无水印媒体下载与云端口播转写。

Actor：
- easyapi~douyin-video-downloader：作品数据 + 无水印 mp4/mp3
- apple_yang~douyin-transcripts-scraper：云端口播转写（备选，--transcriptor apify）

Token 查找顺序：
1. 环境变量 APIFY_TOKEN
2. 环境变量 APIFY_KEYS_FILE 指定的文件（正则 apify_api_ 串）
3. ~/.config/dbs/API_Keys.md 的 ## Apify API 段落
4. macOS 钥匙串服务 dbs-apify-token
5. ~/vibecoding/.credentials.md（本机个人凭证文件，正则 apify_api_ 串）

踩坑备忘：
- easyapi input 字段必须是 links（数组），不是 videoUrls / startUrls
- Apify 月度硬额度超了报 403 platform-feature-disabled，去 console 充值或调高上限
- 视频被下架返回 {"error": true, "message": "No medias found"}
- 并发建议 5-8 个 run 以内，超出报 402 actor-memory-limit-exceeded
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://api.apify.com/v2"
ACTOR_DOWNLOAD = "easyapi~douyin-video-downloader"
ACTOR_TRANSCRIPT = "apple_yang~douyin-transcripts-scraper"
KEYCHAIN_SERVICE = "dbs-apify-token"
DEFAULT_API_KEYS_FILE = Path.home() / ".config" / "dbs" / "API_Keys.md"
PERSONAL_KEYS_FILE = Path.home() / "vibecoding" / ".credentials.md"


class ApifyError(RuntimeError):
    """可向调用方展示、且不包含 token 的错误。"""


def find_token() -> str:
    value = os.environ.get("APIFY_TOKEN", "").strip()
    if value:
        return value

    configured_path = os.environ.get("APIFY_KEYS_FILE", "").strip()
    candidates: list[Path] = []
    if configured_path:
        candidates.append(Path(configured_path).expanduser())
    candidates.append(DEFAULT_API_KEYS_FILE)
    candidates.append(PERSONAL_KEYS_FILE)
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        token = _token_from_text(text)
        if token:
            return token

    if (
        sys.platform == "darwin"
        and os.environ.get("DBS_VIDEO_EXTRACT_DISABLE_KEYCHAIN") != "1"
    ):
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
        else:
            token = result.stdout.strip()
            if token:
                return token
    return ""


def _token_from_text(text: str) -> str:
    match = re.search(r"apify_api_\w+", text)
    return match.group(0) if match else ""


def get_token() -> str:
    value = find_token()
    if value:
        return value
    raise ApifyError(
        "缺少 Apify token：请设置环境变量 APIFY_TOKEN，在 API_Keys.md 添加 "
        "## Apify API 段落（- **Token**: apify_api_xxx），或在 macOS 钥匙串创建 "
        f"服务名为 {KEYCHAIN_SERVICE} 的通用密码。"
    )


def _http_post(url: str, data: dict[str, Any], retries: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            if error.code in (402, 403):
                raise ApifyError(f"Apify HTTP {error.code}：{detail}") from error
            last_error = error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
        if attempt < retries - 1:
            time.sleep(2**attempt)
    raise ApifyError(f"Apify 请求失败：{last_error}") from last_error


def _http_get(url: str, retries: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            if error.code in (402, 403):
                raise ApifyError(f"Apify HTTP {error.code}：{detail}") from error
            last_error = error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
        if attempt < retries - 1:
            time.sleep(2**attempt)
    raise ApifyError(f"Apify 请求失败：{last_error}") from last_error


def start_run(actor: str, payload: dict[str, Any]) -> str:
    token = get_token()
    data = _http_post(f"{BASE}/acts/{actor}/runs?token={token}", payload)
    run_id = (data.get("data") or {}).get("id")
    if not run_id:
        raise ApifyError(f"Apify 起 run 失败，没有返回 run id：{data}")
    return str(run_id)


def wait_run(run_id: str, timeout: float = 420.0, interval: float = 3.0) -> str:
    """轮询 run 状态直到终态，返回 dataset id；失败抛 ApifyError。"""
    token = get_token()
    deadline = time.monotonic() + max(1.0, timeout)
    while True:
        data = _http_get(f"{BASE}/actor-runs/{run_id}?token={token}")
        run = data.get("data") or {}
        status = run.get("status", "")
        if status == "SUCCEEDED":
            dataset_id = run.get("defaultDatasetId")
            if not dataset_id:
                raise ApifyError("Apify run 成功但没有 defaultDatasetId。")
            return str(dataset_id)
        if status in ("FAILED", "TIMED-OUT", "ABORTED"):
            raise ApifyError(
                f"Apify run 终态 {status}"
                + (f"：{run.get('errorMessage')}" if run.get("errorMessage") else "")
            )
        if time.monotonic() >= deadline:
            raise ApifyError("Apify run 轮询超时。")
        time.sleep(max(0.5, interval))


def fetch_items(dataset_id: str) -> list[dict[str, Any]]:
    token = get_token()
    data = _http_get(f"{BASE}/datasets/{dataset_id}/items?clean=true&token={token}")
    if not isinstance(data, list):
        raise ApifyError("Apify dataset items 返回不是数组。")
    return [item for item in data if isinstance(item, dict)]


def fetch_media(url: str, timeout: float = 420.0) -> dict[str, Any]:
    """一次 run 查一条视频的数据与媒体直链。

    返回：{ok, aweme_id, description, duration_ms, mp4_url, mp3_url,
          error(可选), status(可选,如 NO_MEDIAS)}
    """
    run_id = start_run(ACTOR_DOWNLOAD, {"links": [url]})
    dataset_id = wait_run(run_id, timeout)
    items = fetch_items(dataset_id)
    if not items:
        return {"ok": False, "error": "Apify 没有返回条目。"}
    payload = items[0].get("result", items[0])
    if not isinstance(payload, dict):
        payload = {}
    if payload.get("error") or payload.get("message") == "No medias found":
        return {
            "ok": False,
            "status": payload.get("message", "ERROR"),
            "error": str(payload.get("message") or payload.get("error") or "未知错误"),
        }
    medias = payload.get("medias") or []
    if not medias:
        return {
            "ok": False,
            "status": "NO_MEDIAS",
            "error": "没有获取到媒体（视频可能已下架）。",
        }

    def media_url(quality: str | None, media_type: str | None = None) -> str:
        for media in medias:
            if not isinstance(media, dict):
                continue
            if media_type and media.get("type") != media_type:
                continue
            if quality and media.get("quality") != quality:
                continue
            value = media.get("url") or media.get("downloadUrl")
            if value:
                return str(value)
        return ""

    mp4_url = (
        media_url("no_watermark")
        or media_url("hd_no_watermark")
        or media_url(None, "video")
    )
    mp3_url = media_url(None, "audio") or media_url("mp3")
    return {
        "ok": True,
        "aweme_id": str(payload.get("aweme_id") or payload.get("video_id") or payload.get("id") or ""),
        "description": str(
            payload.get("desc") or payload.get("description") or payload.get("title") or ""
        ).strip(),
        "author": str(payload.get("author") or payload.get("nickname") or "").strip(),
        "duration_ms": payload.get("duration"),
        "mp4_url": mp4_url,
        "mp3_url": mp3_url,
    }


def fetch_cloud_transcript(url: str, timeout: float = 420.0) -> dict[str, Any]:
    """备选：apple_yang 云端口播转写（实测可能失效，失败时回落本地 whisper）。"""
    run_id = start_run(ACTOR_TRANSCRIPT, {"videoUrl": url})
    dataset_id = wait_run(run_id, timeout)
    items = fetch_items(dataset_id)
    if not items:
        return {"ok": False, "error": "云端口播 run 没有返回条目。"}
    item = items[0]
    transcript = str(item.get("transcript") or "").strip()
    return {
        "ok": True,
        "transcript": transcript,
        "videoTitle": str(item.get("videoTitle") or "").strip(),
        "author": str(item.get("author") or item.get("authorName") or "").strip(),
        "aweme_id": str(item.get("awemeId") or item.get("videoId") or ""),
        "videoUrl": str(item.get("videoUrl") or "").strip(),
        "duration_seconds": item.get("duration"),
        "empty": not transcript,
    }


def download(url: str, dest: Path, timeout: float = 300.0, retries: int = 3) -> int:
    """下载媒体到 dest，返回字节数；失败抛 ApifyError。"""
    if not url:
        raise ApifyError("媒体直链为空。")
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(response.read())
            return dest.stat().st_size
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            last_error = error
            if attempt < retries - 1:
                time.sleep(2**attempt)
    raise ApifyError(f"媒体下载失败：{last_error}") from last_error


def media_available() -> bool:
    return bool(find_token())


def parse_share_url(value: str) -> str:
    match = re.search(r"https?://[^\s<>\"']+", value)
    if not match:
        raise ApifyError("输入中没有找到 HTTP 或 HTTPS 分享链接。")
    return match.group(0).rstrip("，。！？；：、,.!?;:)]}）】》")


def douyin_video_id(url: str) -> str:
    """从抖音视频 URL 提取 19 位视频 ID，取不到返回空串。"""
    resolved = url
    match = re.search(r"/video/(\d{15,20})", urllib.parse.urlparse(url).path)
    if match:
        return match.group(1)
    try:
        request = urllib.request.Request(
            resolved,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            resolved = response.geturl()
    except (urllib.error.URLError, TimeoutError):
        resolved = url
    match = re.search(r"/video/(\d{15,20})", urllib.parse.urlparse(resolved).path)
    return match.group(1) if match else ""


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Apify 客户端调试入口。")
    parser.add_argument("--check-keys", action="store_true", help="只检查 token 发现状态")
    parser.add_argument("url", nargs="?", help="抖音视频链接或分享文案")
    parser.add_argument("--transcript", action="store_true", help="云端转写（备选）")
    args = parser.parse_args()

    if args.check_keys:
        print(json.dumps({"apify_configured": bool(find_token())}, ensure_ascii=False))
        raise SystemExit(0 if find_token() else 2)
    if not args.url:
        raise SystemExit("需要提供链接或 --check-keys。")
    share_url = parse_share_url(args.url)
    if args.transcript:
        print(json.dumps(fetch_cloud_transcript(share_url), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(fetch_media(share_url), ensure_ascii=False, indent=2))
