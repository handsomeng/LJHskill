#!/usr/bin/env python3
"""短视频提取整合入口（瀚森完整版）。

默认流程：抖音链接/分享文案 → Apify 取数据 + 无水印 mp4/mp3 → 本地 whisper 转写口播
→ 按作者和标题归档 Markdown。小红书 / 视频号走 TikHub 数据 + 轻抖文稿。
支持批量（--input-file / 多个输入），每条结果汇总进 {输出目录}/_index.json，
供 build_report.py 生成分析报告。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import apify_api as apify
import extract_video_transcript as transcript
import tikhub_api as tikhub


class CombinedError(RuntimeError):
    """可向调用方展示的整合流程错误。"""


LEGAL_NOTICE = (
    "LJHskill 是免费开源项目，与 TikHub、轻抖无隶属、合作或利益关系。"
    "充值由用户自主决定，相关交易、服务、争议及风险由用户自行承担；"
    "法律另有规定的除外，LJHskill 不承担责任。"
)
PURCHASE_URLS = {
    "TikHub": "https://user.tikhub.io/dashboard/add-credit",
    "轻抖": "https://www.qingdou.vip/voice-text-api",
}
API_KEY_EXPLANATION = (
    "想让这个 Skill 工作，需要先开通外部数据服务。API Key 是服务商在开通后"
    "提供的一串使用凭证，可以理解为这个 Skill 调用服务的专用通行证。"
    "你不需要理解技术原理，也不要把它发到聊天中。"
)
PURCHASE_CHOICES = {
    "完整功能": {
        "providers": ["TikHub", "轻抖"],
        "result": "同时获得作品／账号数据和语音文字稿",
    },
    "只看数据": {
        "providers": ["TikHub"],
        "result": "获得作者、标题、点赞、评论等作品／账号数据",
    },
    "只要文字稿": {
        "providers": ["轻抖"],
        "result": "把短视频口播提取成文字稿",
    },
}
PURCHASE_STEPS = [
    "按需要的结果选择完整功能、只看数据或只要文字稿。",
    "打开对应充值地址，在服务商页面注册或登录。",
    "查看页面当前显示的套餐、额度、有效期和计费规则，自主决定是否充值。",
    "充值后进入个人中心，寻找 API Key、密钥管理或开发者设置；需要时创建并复制凭证。",
    "不要把凭证发送到聊天中；只需回复 TikHub 已充值、轻抖已充值或两个都已充值。",
    "随后在本地终端运行安全配置脚本，并重新检查服务状态。",
]
SETUP_COMMANDS = {
    "TikHub": "python3 scripts/configure_api_key.py tikhub",
    "轻抖": "python3 scripts/configure_api_key.py qingdou",
    "Apify": "python3 scripts/configure_api_key.py apify",
}
WHISPER_PYTHON_CANDIDATES = (
    Path.home() / ".workbuddy" / "skills" / "douyin-video-teardown" / ".venv" / "bin" / "python",
    Path.home() / ".claude" / "skills" / "douyin-video-teardown" / ".venv" / "bin" / "python",
    Path.home() / ".codex" / "skills" / "douyin-video-teardown" / ".venv" / "bin" / "python",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="提取短视频数据、口播文稿与媒体，支持批量并汇总索引。"
    )
    parser.add_argument("input", nargs="?", help="短视频链接或完整分享文案")
    parser.add_argument(
        "--input-file", type=Path, help="UTF-8 文件，每个非空行一条链接或分享文案"
    )
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取分享文案")
    parser.add_argument(
        "--check-keys",
        action="store_true",
        help="只检查凭证发现状态，不读取输入或发起网络请求",
    )
    parser.add_argument(
        "--intro",
        action="store_true",
        help="输出开场引导信息（能力菜单 + 凭证状态 + 示例），不读取输入",
    )
    parser.add_argument(
        "--mode",
        choices=("both", "data", "transcript"),
        default="both",
        help="默认同时查询数据和提取文字稿",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd() / "短视频文字稿",
        help="Markdown 输出根目录",
    )
    parser.add_argument("--overwrite", action="store_true", help="覆盖同源文稿")
    parser.add_argument(
        "--source",
        choices=("auto", "app", "web"),
        default="auto",
        help="TikHub 抖音作品数据源；小红书与视频号忽略此参数",
    )
    parser.add_argument("--raw-data", action="store_true", help="保留 TikHub 完整响应")
    parser.add_argument(
        "--data-timeout", type=float, default=15.0, help="TikHub 请求超时秒数"
    )
    parser.add_argument(
        "--poll-interval", type=float, default=2.0, help="轻抖轮询间隔秒数"
    )
    parser.add_argument(
        "--transcript-timeout", type=float, default=900.0, help="轻抖最长等待秒数"
    )
    parser.add_argument(
        "--download-media",
        action="store_true",
        help="媒体默认下载（转写需要音轨）；本参数保留兼容",
    )
    parser.add_argument(
        "--transcriptor",
        choices=("auto", "whisper", "apify"),
        default="auto",
        help="口播转写通道：auto=本地 whisper 优先、云 actor 兜底；whisper=仅本地；apify=仅云端",
    )
    parser.add_argument(
        "--whisper-model", default="small", help="本地 whisper 模型，默认 small"
    )
    parser.add_argument(
        "--concurrency", type=int, default=2, help="批量并发数，默认 2"
    )
    return parser.parse_args()


def collect_inputs(args: argparse.Namespace) -> list[str]:
    values = [value.strip() for value in ([args.input] if args.input else []) if value.strip()]
    if args.stdin:
        value = sys.stdin.read().strip()
        if value:
            values.append(value)
    if args.input_file:
        content = args.input_file.expanduser().read_text(encoding="utf-8")
        values.extend(line.strip() for line in content.splitlines() if line.strip())
    values = list(dict.fromkeys(values))
    if not values:
        raise CombinedError("没有收到短视频链接或分享文案。")
    return values


def credential_summary() -> dict[str, Any]:
    has_tikhub = bool(tikhub.find_api_key())
    has_qingdou = bool(transcript.find_api_key())
    has_apify = bool(apify.find_token())
    data_ok = has_tikhub or has_apify
    transcript_ok = has_qingdou or has_apify
    if data_ok and transcript_ok:
        if has_apify:
            state = "apify_ready" if not (has_tikhub or has_qingdou) else "complete"
            if state == "apify_ready":
                message = (
                    "Apify 已配置：抖音作品数据、口播文稿与媒体下载可直接使用。"
                    "TikHub 与轻抖未配置，小红书和微信视频号暂不可用。"
                )
            elif has_tikhub and has_qingdou:
                message = (
                    "Apify、TikHub 与轻抖密钥均已配置：全平台数据与文稿可用。"
                )
            else:
                message = "Apify 与部分第三方密钥已配置，抖音能力完整。"
        else:
            state = "complete"
            message = "TikHub 与轻抖 API Key 均已配置，可以查询数据并提取文字稿。"
    elif has_apify:
        state = "apify_only"
        message = (
            "Apify 已配置，可以完整提取抖音（数据 + 口播 + 媒体）。"
            "TikHub 与轻抖未配置，小红书和微信视频号不可用。"
        )
    elif has_tikhub:
        state = "data_only"
        message = (
            "TikHub 已经可以使用：能查询作品或账号数据。轻抖尚未开通，"
            "所以暂时不能生成语音文字稿。"
        )
    elif has_qingdou:
        state = "transcript_only"
        message = (
            "轻抖已经可以使用：能生成语音文字稿。TikHub 尚未开通，"
            "所以暂时不能查询作品或账号数据。"
        )
    else:
        state = "unavailable"
        message = (
            "当前没有可用的外部服务凭证。如果不购买并配置至少一个服务，"
            "这个 Skill 无法使用。"
        )
    summary: dict[str, Any] = {
        "credential_state": state,
        "tikhub_configured": has_tikhub,
        "qingdou_configured": has_qingdou,
        "apify_configured": has_apify,
        "message": message,
    }
    missing_providers: list[str] = []
    if not has_tikhub and not has_apify:
        missing_providers.append("TikHub")
    if not has_qingdou and not has_apify:
        missing_providers.append("轻抖")
    if missing_providers:
        summary["purchase_required_to_use"] = not has_tikhub and not has_qingdou and not has_apify
        summary["purchase_required_for_full_functionality"] = bool(missing_providers)
        summary["api_key_explanation"] = API_KEY_EXPLANATION
        summary["purchase_choices"] = PURCHASE_CHOICES
        summary["legal_notice"] = LEGAL_NOTICE
        summary["purchase_urls"] = {
            provider: PURCHASE_URLS[provider] for provider in missing_providers
        }
        summary["purchase_steps"] = PURCHASE_STEPS
        summary["setup_commands"] = {
            provider: SETUP_COMMANDS[provider] for provider in missing_providers
        }
    return summary


def build_intro() -> dict[str, Any]:
    """开场引导：能力菜单 + 凭证状态 + 示例（AI 据此转成自然语言介绍）。"""
    credentials = credential_summary()
    return {
        "intro": True,
        "credentials": credentials,
        "capabilities": [
            {
                "id": "video",
                "title": "单条导出视频",
                "detail": "给一条抖音链接或分享文案，返回无水印 mp4 + 原声 mp3 + 作者/标题/时长数据",
                "example": "python3 scripts/extract_video.py \"链接\" --output-dir 输出目录",
            },
            {
                "id": "transcript",
                "title": "单条导出脚本",
                "detail": "同一条链接同时出口播文稿，Markdown 按作者/标题归档，本地 whisper 转写免费",
                "example": "python3 scripts/extract_video.py \"链接\" --output-dir 输出目录",
            },
            {
                "id": "batch",
                "title": "批量提取",
                "detail": "links.txt 每行一条，并发提取脚本 + mp4 + 数据，结果写入 _index.json",
                "example": "python3 scripts/extract_video.py --input-file links.txt --output-dir 输出目录",
            },
            {
                "id": "report",
                "title": "分析报告",
                "detail": "批量提取完成后生成统计报告：样本概览、时长/字数、口播词频、跨视频重复话术、开场钩子、促销信号词",
                "example": "python3 scripts/build_report.py 输出目录",
            },
        ],
        "platforms": {
            "抖音": "Apify 通道（数据 + 视频 + 口播，仅需 Apify token）",
            "小红书": "TikHub 数据 + 轻抖文稿（需配置两家 Key）",
            "微信视频号": "TikHub 数据 + 轻抖文稿（需配置两家 Key）",
        },
        "setup_guide": "缺少凭证时按 references/api-setup.md 引导购买与配置；Apify 接入见 references/apify-api.md",
        "usage": "直接把链接或整段分享文案丢过来即可，不需要手动解析短链。",
    }


def missing_credential_part(provider: str, capability: str) -> dict[str, Any]:
    return {
        "ok": False,
        "missing_api_key": True,
        "provider": provider,
        "error": f"缺少 {provider} API Key，当前无法{capability}。",
    }


# ---------- 原 TikTok / 轻抖 路径（保留） ----------


def run_data(user_input: str, args: argparse.Namespace) -> dict[str, Any]:
    try:
        share_url = tikhub.extract_share_url(user_input)
    except tikhub.TikHubError as error:
        return {"ok": False, "error": str(error)}
    if not tikhub.detect_platform(share_url):
        return {
            "ok": None,
            "skipped": True,
            "reason": "当前 TikHub 数据解析只支持抖音、小红书和微信视频号链接。",
        }
    try:
        return tikhub.fetch_supported_link_mcp(
            tikhub.get_api_key(),
            share_url,
            args.source,
            max(1.0, args.data_timeout),
            args.raw_data,
        )
    except (tikhub.TikHubError, OSError) as error:
        return {"ok": False, "error": str(error)}


def apply_data_fallbacks(
    item: dict[str, Any], data_result: dict[str, Any] | None
) -> dict[str, Any]:
    enriched = dict(item)
    if not data_result or data_result.get("link_type") != "video":
        return enriched
    summary = data_result.get("response")
    if not isinstance(summary, dict) or "response" in summary:
        return enriched
    if not transcript.find_author(enriched) and summary.get("author"):
        enriched["authorName"] = summary["author"]
    if not str(enriched.get("videoTitle") or "").strip() and summary.get("description"):
        enriched["videoTitle"] = summary["description"]
    if not (enriched.get("awemeId") or enriched.get("videoId")):
        video_id = summary.get("aweme_id") or summary.get("video_id")
        if video_id:
            enriched["videoId"] = video_id
    return enriched


def run_transcript(
    user_input: str,
    args: argparse.Namespace,
    data_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        api_key = transcript.get_api_key()
        base_url = os.environ.get(
            "QINGDOU_BASE_URL", transcript.DEFAULT_BASE_URL
        ).strip()
        batch_id = transcript.commit_task(base_url, api_key, user_input)
        result = transcript.poll_task(
            base_url,
            api_key,
            batch_id,
            max(0.2, args.poll_interval),
            max(1.0, args.transcript_timeout),
        )
        items = result.get("list")
        if not isinstance(items, list) or not items:
            raise transcript.ExtractError("批任务没有返回文稿条目。")
        item_results = [
            transcript.save_item(
                apply_data_fallbacks(item, data_result),
                args.output_dir,
                args.overwrite,
            )
            for item in items
            if isinstance(item, dict)
        ]
        if not item_results:
            raise transcript.ExtractError("批任务没有返回可处理的文稿条目。")
        success_count = sum(1 for item in item_results if item.get("ok"))
        return {
            "ok": success_count == len(item_results),
            "success_count": success_count,
            "failure_count": len(item_results) - success_count,
            "items": item_results,
        }
    except (transcript.ExtractError, OSError) as error:
        return {"ok": False, "error": str(error)}


# ---------- Apify 抖音路径（瀚森完整版新增） ----------


def find_whisper_python() -> str:
    configured = os.environ.get("LJH_WHISPER_PYTHON", "").strip()
    candidates = ([Path(configured).expanduser()] if configured else []) + list(
        WHISPER_PYTHON_CANDIDATES
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return ""


def transcribe_with_whisper(
    whisper_python: str, mp3: Path, output_dir: Path, model: str
) -> dict[str, Any]:
    out_text = output_dir / "transcripts" / f"{mp3.stem}.txt"
    script = Path(__file__).resolve().parent / "transcribe_mp3.py"
    try:
        completed = subprocess.run(
            [whisper_python, str(script), str(mp3), str(out_text), model],
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"ok": False, "error": f"本地转写进程失败：{error}"}
    if completed.returncode != 0:
        # faster-whisper 退出崩溃发生在结果写出之后；stdout 有合法 JSON 时仍算成功
        try:
            payload = json.loads(completed.stdout.strip().splitlines()[-1])
            if payload.get("ok"):
                return {
                    "ok": True,
                    "transcript": str(payload["transcript"]),
                    "post_exit_crash": True,
                }
        except (json.JSONDecodeError, IndexError):
            pass
        return {
            "ok": False,
            "error": f"本地转写失败：{(completed.stderr or completed.stdout)[-300:]}",
        }
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"ok": False, "error": "本地转写输出无法解析。"}
    if not payload.get("ok"):
        return {"ok": False, "error": str(payload.get("error") or "本地转写失败")}
    return {"ok": True, "transcript": str(payload["transcript"])}


def extract_audio_from_mp4(
    whisper_python: str, mp4: Path, output_dir: Path
) -> dict[str, Any]:
    """从 mp4 抽音轨到 {输出目录}/media/{stem}.mp3，返回路径或错误。"""
    out_mp3 = output_dir / "media" / f"{mp4.stem}.mp3"
    script = Path(__file__).resolve().parent / "extract_audio.py"
    try:
        completed = subprocess.run(
            [whisper_python, str(script), str(mp4), str(out_mp3)],
            capture_output=True,
            text=True,
            timeout=900,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"ok": False, "error": f"抽音轨进程失败：{error}"}
    if completed.returncode != 0:
        return {
            "ok": False,
            "error": f"抽音轨失败：{(completed.stderr or completed.stdout)[-300:]}",
        }
    if not out_mp3.is_file() or out_mp3.stat().st_size < 1000:
        return {"ok": False, "error": "抽出的音轨文件为空。"}
    return {"ok": True, "path": str(out_mp3)}


def run_apify_extract(
    user_input: str, args: argparse.Namespace
) -> dict[str, Any]:
    """单条抖音：Apify 数据 + 媒体下载 + 口播转写 + Markdown 归档。"""
    try:
        share_url = apify.parse_share_url(user_input)
    except apify.ApifyError as error:
        return {"ok": False, "error": str(error)}
    if tikhub.detect_platform(share_url) != "douyin":
        return {
            "ok": None,
            "skipped": True,
            "reason": "Apify 通道只支持抖音链接，其他平台请使用 TikHub / 轻抖。",
        }

    try:
        media = apify.fetch_media(share_url)
    except apify.ApifyError as error:
        return {"ok": False, "error": str(error)}
    if not media.get("ok"):
        return {"ok": False, **{k: media[k] for k in ("status", "error") if k in media}}

    video_id = media.get("aweme_id") or apify.douyin_video_id(share_url)
    media_dir = args.output_dir.expanduser().resolve() / "media"
    mp4_path = mp3_path = None
    wants_media = args.mode in ("both", "transcript") or args.download_media
    if wants_media and media.get("mp4_url"):
        try:
            mp4_path = media_dir / f"{video_id or 'video'}.mp4"
            apify.download(media.get("mp4_url"), mp4_path)
        except apify.ApifyError as error:
            mp4_path = None

    transcript_mode = args.transcriptor
    transcript_text = ""
    transcript_source = ""
    transcript_error = ""
    whisper_python = find_whisper_python()
    if args.mode in ("both", "transcript"):
        if transcript_mode in ("auto", "whisper") and mp4_path and whisper_python:
            # audio 直链实测可能返回错误内容（与视频时长不符），音轨一律从 mp4 抽取
            audio_result = extract_audio_from_mp4(
                whisper_python, mp4_path, args.output_dir.expanduser().resolve()
            )
            if audio_result.get("ok"):
                mp3_path = Path(audio_result["path"])
            else:
                transcript_error = audio_result.get("error", "")
            if mp3_path:
                result = transcribe_with_whisper(
                    whisper_python, mp3_path, args.output_dir.expanduser().resolve(),
                    args.whisper_model,
                )
                if result.get("ok"):
                    transcript_text = result["transcript"]
                    transcript_source = "whisper_local"
                else:
                    transcript_error = result.get("error", "")
        elif transcript_mode in ("auto", "whisper"):
            transcript_error = (
                "未找到本地 whisper 环境，尝试云端转写。"
                if not whisper_python
                else transcript_error
            )
        if not transcript_text and transcript_mode in ("auto", "apify"):
            try:
                cloud = apify.fetch_cloud_transcript(share_url)
                if cloud.get("ok"):
                    transcript_text = cloud.get("transcript", "")
                    transcript_source = "apify_cloud"
                    if not media.get("description") and cloud.get("videoTitle"):
                        media["description"] = cloud["videoTitle"]
                else:
                    transcript_error = cloud.get("error", "")
            except apify.ApifyError as error:
                transcript_error = str(error)
    if transcript_source == "whisper_local" and not transcript_text:
        transcript_error = "本地转写完成但口播为空（可能纯 BGM / 卡点视频）。"

    duration_seconds = None
    if isinstance(media.get("duration_ms"), (int, float)):
        duration_seconds = round(float(media["duration_ms"]) / 1000, 1)
    description = media.get("description") or ""
    wants_transcript = args.mode in ("both", "transcript")
    markdown_saved = False
    saved: dict[str, Any] | None = None
    if wants_transcript:
        item = {
            "status": 1000,
            "videoContent": transcript_text,
            "videoTitle": description or f"未命名视频-{video_id or '未知ID'}",
            "originLink": share_url,
            "awemeId": video_id,
            "platformName": "抖音",
            "videoTime": duration_seconds,
            "authorName": media.get("author") or "",
            "videoCover": "",
        }
        saved = transcript.save_item(item, args.output_dir, args.overwrite)
        markdown_saved = bool(saved.get("ok"))
    return {
        # ok 表示「数据与媒体提取成功」；口播为空是如实标记，不算失败
        "ok": True,
        "markdown_saved": markdown_saved,
        "provider": "apify",
        "source": transcript_source or "none",
        "action": saved.get("action") if saved else None,
        "path": saved.get("path") if saved else None,
        "title": saved.get("title") if saved else (description or None),
        "author": saved.get("author") if saved else (media.get("author") or None),
        "url": share_url,
        "video_id": video_id,
        "duration_seconds": duration_seconds,
        "transcript": transcript_text,
        "transcript_empty": not transcript_text,
        "transcript_error": transcript_error,
        "media": {
            "mp4": str(mp4_path) if mp4_path else None,
            "mp3": str(mp3_path) if mp3_path else None,
        },
        "raw": media,
    }


def run_legacy_extract(user_input: str, args: argparse.Namespace) -> dict[str, Any]:
    """非 Apify 路径：TikHub 数据（可用时）+ 轻抖文稿（可用时）。"""
    credentials = credential_summary()
    result: dict[str, Any] = {"provider": "tikhub_qingdou"}
    parts: list[dict[str, Any]] = []
    data_result: dict[str, Any] | None = None
    if args.mode in ("both", "data"):
        if credentials["tikhub_configured"]:
            data_result = run_data(user_input, args)
        else:
            data_result = missing_credential_part("TikHub", "查询作品或账号数据")
        result["data"] = data_result
        parts.append(data_result)
    if args.mode in ("both", "transcript"):
        if not credentials["qingdou_configured"]:
            result["transcript"] = missing_credential_part("轻抖", "提取语音文字稿")
        elif args.mode == "both" and data_result and data_result.get("link_type") == "user":
            result["transcript"] = {
                "ok": None,
                "skipped": True,
                "reason": "链接指向用户主页，没有可提取的单条视频文稿。",
            }
        else:
            result["transcript"] = run_transcript(user_input, args, data_result)
        parts.append(result["transcript"])
    ok, partial_success = overall_status(parts)
    result["ok"] = ok
    result["partial_success"] = partial_success
    return result


def normalize_share_url(url: str) -> str:
    """把 iesdouyin.com 分享链接归一化为 www.douyin.com/video/{id}。"""
    import urllib.parse

    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if hostname == "iesdouyin.com" or hostname.endswith(".iesdouyin.com"):
        match = re.search(r"/share/(?:video|note|slides)/(\d+)", parsed.path)
        if match:
            return f"https://www.douyin.com/video/{match.group(1)}"
    return url


def overall_status(parts: list[dict[str, Any]]) -> tuple[bool, bool]:
    attempted = [part for part in parts if not part.get("skipped")]
    successes = [part for part in attempted if part.get("ok") is True]
    failures = [part for part in attempted if part.get("ok") is False]
    return bool(successes) and not failures, bool(successes) and bool(failures)


def update_index(output_dir: Path, entries: list[dict[str, Any]]) -> Path:
    """把本次结果合并进 {输出目录}/_index.json（按 url 去重），返回索引路径。"""
    resolved = output_dir.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    index_path = resolved / "_index.json"
    existing: dict[str, Any] = {}
    if index_path.is_file():
        try:
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
            existing = loaded.get("items") if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            existing = {}
    for entry in entries:
        key = str(entry.get("url") or entry.get("input") or "").strip()
        if not key:
            continue
        existing[key] = entry
    payload = {
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "count": len(existing),
        "items": existing,
    }
    index_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return index_path


def summarize(entries: list[dict[str, Any]], index_path: Path) -> dict[str, Any]:
    success = [entry for entry in entries if entry.get("ok")]
    failed = [entry for entry in entries if not entry.get("ok") and not entry.get("skipped")]
    return {
        "ok": not failed,
        "total": len(entries),
        "success_count": len(success),
        "failure_count": len(failed),
        "index_path": str(index_path),
        "results": entries,
    }


def main() -> int:
    args = parse_args()
    credentials = credential_summary()
    if args.check_keys:
        print(json.dumps(credentials, ensure_ascii=False, indent=2))
        return 0 if credentials["credential_state"] != "unavailable" else 2
    if args.intro:
        print(json.dumps(build_intro(), ensure_ascii=False, indent=2))
        return 0 if credentials["credential_state"] != "unavailable" else 2

    try:
        inputs = collect_inputs(args)
    except (CombinedError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 2

    needs_data = args.mode in ("both", "data")
    needs_transcript = args.mode in ("both", "transcript")
    if not (
        (needs_data and (credentials["tikhub_configured"] or credentials["apify_configured"]))
        or (needs_transcript and (credentials["qingdou_configured"] or credentials["apify_configured"]))
    ):
        print(
            json.dumps(
                {
                    "ok": False,
                    "mode": args.mode,
                    **credentials,
                    "next_step": (
                        "先按需要的结果选择服务并完成充值。充值后不要发送凭证，"
                        "只需回复已充值，再按 setup_commands 在本地安全保存并复查状态。"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    entries: list[dict[str, Any]] = []

    def extract_one(user_input: str) -> dict[str, Any]:
        if args.mode == "transcript" and not credentials["qingdou_configured"]:
            if credentials["apify_configured"]:
                return run_apify_extract(user_input, args)
            return missing_credential_part("轻抖", "提取语音文字稿")
        try:
            share_url = tikhub.extract_share_url(user_input)
        except tikhub.TikHubError:
            share_url = user_input
        share_url = normalize_share_url(share_url)
        platform = tikhub.detect_platform(share_url)
        use_apify = platform == "douyin" and credentials["apify_configured"]
        if use_apify:
            return run_apify_extract(user_input, args)
        return run_legacy_extract(user_input, args)

    concurrency = max(1, min(6, args.concurrency)) if len(inputs) > 1 else 1
    if concurrency == 1:
        entries = [extract_one(user_input) for user_input in inputs]
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(extract_one, user_input): user_input
                for user_input in inputs
            }
            ordered: dict[str, dict[str, Any]] = {}
            for future in as_completed(futures):
                try:
                    ordered[futures[future]] = future.result()
                except Exception as error:  # noqa: BLE001
                    ordered[futures[future]] = {
                        "input": futures[future], "ok": False, "error": f"{error}",
                    }
            entries = [ordered[user_input] for user_input in inputs if user_input in ordered]

    try:
        index_path = update_index(args.output_dir, entries)
    except OSError as error:
        index_path = Path("")
        entries = [{**entry, "index_error": str(error)} for entry in entries]

    summary = summarize(entries, index_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
