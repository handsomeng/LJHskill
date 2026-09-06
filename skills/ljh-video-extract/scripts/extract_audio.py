#!/usr/bin/env python3
"""从 mp4 抽取音轨为 mp3（用 imageio-ffmpeg 自带的 ffmpeg 二进制）。

必须用安装了 imageio-ffmpeg 的 venv python 运行（douyin-video-teardown 的 .venv）。
原因：easyapi 的 audio 直链现在可能返回错误内容（实测下载到的音频时长与视频不符），
从无水印 mp4 抽音轨最可靠。

用法：
  python extract_audio.py <mp4 路径> <输出 mp3 路径>
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def find_ffmpeg() -> str:
    import shutil

    configured = __import__("os").environ.get("DBS_FFMPEG", "").strip()
    if configured:
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, OSError):
        raise SystemExit(
            "找不到 ffmpeg：请设置环境变量 DBS_FFMPEG，或安装 imageio-ffmpeg。"
        )


def main() -> int:
    if len(sys.argv) < 3:
        print("用法：python extract_audio.py <mp4> <out.mp3>")
        return 2
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    if not source.is_file():
        print(json.dumps({"ok": False, "error": f"找不到文件：{source}"}))
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg()
    try:
        completed = subprocess.run(
            [
                ffmpeg, "-y",
                "-i", str(source),
                "-vn",
                "-ac", "2",
                "-q:a", "2",
                str(target),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "error": f"ffmpeg 启动失败：{error}"}))
        return 2
    if completed.returncode != 0 or not target.is_file():
        tail = (completed.stderr or "")[-400:]
        print(json.dumps({"ok": False, "error": f"抽音轨失败：{tail}"}))
        return 2
    print(json.dumps({"ok": True, "output": str(target), "bytes": target.stat().st_size}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
