#!/usr/bin/env python3
"""用 faster-whisper 把 mp3 转写成中文口播文字。

必须用装了 faster-whisper 的 venv python 运行（discover_whisper_python 会找
douyin-video-teardown 的 .venv）。模型缓存复用 ~/.cache/douyin-teardown/whisper。

用法：
  python transcribe_mp3.py <mp3 路径> <输出 text 路径> [模型大小，默认 small]

输出：
  <text 路径>：全文（纯文本）
  <text 路径>.json：带时间码 segments
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_CACHE = Path.home() / ".cache" / "douyin-teardown" / "whisper"
_LEGACY = Path.home() / "Desktop" / "codex_video_read" / "whisper_models"


def _model_cache() -> Path:
    return _LEGACY if _LEGACY.exists() else _CACHE


def main() -> int:
    if len(sys.argv) < 3:
        print("用法：python transcribe_mp3.py <mp3> <out.txt> [模型大小]")
        return 2
    mp3 = Path(sys.argv[1])
    out_text = Path(sys.argv[2])
    model_size = sys.argv[3] if len(sys.argv) > 3 else "small"
    if not mp3.is_file():
        print(f"找不到音频：{mp3}")
        return 2

    os.environ.setdefault("HF_HOME", str(_model_cache()))
    from faster_whisper import WhisperModel

    cache_dir = str(_model_cache())
    _model_cache().mkdir(parents=True, exist_ok=True)
    print(f"加载模型：{model_size}", file=sys.stderr)
    model = WhisperModel(model_size, device="cpu", compute_type="int8", download_root=cache_dir)

    started = time.time()
    segments, _info = model.transcribe(
        str(mp3),
        language="zh",
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400),
        initial_prompt="以下是普通话带货口播：",
    )
    segs = [
        {"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()}
        for seg in segments
    ]
    text = "".join(seg["text"] for seg in segs)
    out_text.parent.mkdir(parents=True, exist_ok=True)
    out_text.write_text(text, encoding="utf-8")
    out_text.with_suffix(out_text.suffix + ".json").write_text(
        json.dumps(segs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{time.time() - started:.1f}s，{len(segs)} 段，{len(text)} 字", file=sys.stderr)
    sys.stdout.flush()
    print(json.dumps({"ok": True, "transcript": text, "segments_count": len(segs)}))
    sys.stdout.flush()
    # faster-whisper / CTranslate2 在 macOS 上进程退出时偶发
    # "recursive_mutex lock failed" 崩溃（转写结果已写出）。直接退出跳过
    # C++ 对象析构，避免把已完成的任务误判为失败。
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
