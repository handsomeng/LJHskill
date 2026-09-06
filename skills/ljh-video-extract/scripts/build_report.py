#!/usr/bin/env python3
"""从 {输出目录}/_index.json 生成短视频提取分析报告（Markdown）。

用法：
  python3 build_report.py <输出目录> [--out 报告路径]

报告内容：样本概览、时长与文稿统计、口播词频、跨视频重复话术、
每条前 40 字钩子、促销信号词、标题关键词。数据全部来自提取时汇总的索引，
不重新联网。
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import jieba

    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False

STOPWORDS = {
    "我们", "你们", "他们", "她们", "大家", "这个", "那个", "什么", "怎么",
    "就是", "真的", "现在", "可以", "一个", "没有", "因为", "所以", "然后",
    "还有", "如果", "自己", "东西", "时候", "感觉", "非常", "特别", "其实",
    "可能", "已经", "还是", "这样", "那样", "一下", "一点", "直接", "今天",
    "明天", "之前", "以后", "最后", "首先", "其次", "但是", "而且", "或者",
    "里面", "出来", "下来", "起来", "过来", "回去", "开始", "结束", "想要",
    "需要", "一定", "全都", "都是", "不是", "也是", "就是", "都会", "就是",
    "是不是", "姐妹们", "宝贝们", "家人们", "朋友们", "看一下", "听一下",
    "试一下", "用一下", "来一下", "给大家", "跟你们", "对我们", "对皮肤",
}
PROMOTION_WORDS = (
    "优惠", "折扣", "秒杀", "限时", "限量", "买一送一", "满减", "立减", "包邮",
    "免单", "返现", "赠品", "赠", "券", "9.9", "19.9", "29.9", "39.9", "49.9",
    "59.9", "69.9", "99", "专享", "下单", "拍下", "库存", "抢", "福利", "补贴",
    "直播间", "点链接", "小黄车",
)


def load_index(input_dir: Path) -> list[dict[str, Any]]:
    index_path = input_dir / "_index.json"
    if not index_path.is_file():
        raise SystemExit(f"找不到索引文件：{index_path}。请先运行 extract_video.py。")
    data = __import__("json").loads(index_path.read_text(encoding="utf-8"))
    items = data.get("items", {}) if isinstance(data, dict) else {}
    if isinstance(items, dict):
        return list(items.values())
    return list(items)


def chinese_chunks(text: str) -> list[str]:
    """连续中文字符串，供无 jieba 时降级统计。"""
    if JIEBA_AVAILABLE:
        return [
            word
            for word in jieba.lcut(text)
            if re.fullmatch(r"[\u4e00-\u9fff]{2,6}", word)
        ]
    return [
        word
        for run in re.findall(r"[\u4e00-\u9fff]{2,}", text)
        for word in re.findall(r"[\u4e00-\u9fff]{2}", run)
    ]


def word_frequency(entries: list[dict[str, Any]], limit: int = 40) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for entry in entries:
        words = chinese_chunks(str(entry.get("transcript") or ""))
        for word in words:
            if word in STOPWORDS or len(word) < 2:
                continue
            counter[word] += 1
    return counter.most_common(limit)


def repeated_phrases(
    entries: list[dict[str, Any]], min_length: int = 6
) -> list[dict[str, Any]]:
    """跨视频重复出现的连续中文片段（滑动窗口匹配，去掉长窗口的子串）。"""
    window_hits: dict[str, set[str]] = {}
    for entry in entries:
        text = re.sub(r"[^\u4e00-\u9fff]", "", str(entry.get("transcript") or ""))
        url = str(entry.get("url") or entry.get("input") or "")
        for start in range(0, max(0, len(text) - min_length + 1)):
            window = text[start : start + min_length]
            if window in STOPWORDS:
                continue
            window_hits.setdefault(window, set())
            if url:
                window_hits[window].add(url)
    hits = [
        (window, len(urls), urls)
        for window, urls in window_hits.items()
        if len(urls) >= 2
    ]
    if not hits:
        return []
    hits.sort(key=lambda item: (-item[1], -len(item[0])))
    kept: list[tuple[str, int, set[str]]] = []
    for window, count, urls in hits:
        if any(window in other for other, _count, _urls in kept):
            continue
        # 相邻滑窗（4 字以上重叠）视为同一条重复句式，只保留一个代表
        if any(
            window[:4] in other or window[-4:] in other
            for other, _count, _urls in kept
        ):
            continue
        kept.append((window, count, urls))
        if len(kept) >= 30:
            break
    return [
        {"phrase": window, "count": count, "urls": sorted(urls)}
        for window, count, urls in kept
    ]


def hooks(entries: list[dict[str, Any]], limit_chars: int = 40) -> list[dict[str, Any]]:
    """每条口播的前 N 字，作为钩子示例。"""
    result = []
    for entry in entries:
        text = str(entry.get("transcript") or "").strip()
        if not text:
            continue
        result.append(
            {"hook": text[:limit_chars], "url": str(entry.get("url") or entry.get("input") or "")}
        )
    return result


def build_report(entries: list[dict[str, Any]]) -> str:
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    ok_entries = [entry for entry in entries if entry.get("ok") or entry.get("transcript")]
    failed = [entry for entry in entries if not (entry.get("ok") or entry.get("transcript"))]
    transcripts = [
        str(entry.get("transcript") or "").strip()
        for entry in ok_entries
    ]
    transcripts = [text for text in transcripts if text]
    empty_count = len(ok_entries) - len(transcripts)

    authors = Counter(str(entry.get("author") or "_未识别作者") for entry in ok_entries)
    durations = [
        float(entry["duration_seconds"])
        for entry in ok_entries
        if isinstance(entry.get("duration_seconds"), (int, float))
    ]
    all_text = "".join(transcripts)
    frequencies = word_frequency(ok_entries)
    repeats = repeated_phrases(ok_entries)
    promotion = Counter()
    for text in transcripts:
        for word in PROMOTION_WORDS:
            count = text.count(word)
            if count:
                promotion[word] += count

    lines: list[str] = [
        "# 短视频拆解分析报告",
        "",
        f"生成时间：{now}",
        "",
        "## 一、样本概览",
        "",
        f"- 提取总条数：{len(entries)}",
        f"- 成功取到文稿：{len(transcripts)} 条，空口播（BGM/卡点等）：{empty_count} 条",
        f"- 失败：{len(failed)} 条",
        "",
        "| 作者 | 标题 | 时长(秒) | 文稿字数 |",
        "| --- | --- | ---: | ---: |",
    ]
    for entry in ok_entries:
        title = str(entry.get("title") or "").replace("|", "\\|")
        lines.append(
            f"| {entry.get('author') or '_未识别作者'} | {title[:40]} | "
            f"{entry.get('duration_seconds') or ''} | {len(str(entry.get('transcript') or ''))} |"
        )
    if failed:
        lines.append("")
        lines.append("### 失败条目")
        for entry in failed:
            lines.append(
                f"- {entry.get('url') or entry.get('input')}：{entry.get('error') or entry.get('status') or '未知原因'}"
            )
    if transcripts:
        lines.extend(
            [
                "",
                "## 二、时长与文稿统计",
                "",
                f"- 平均时长：{sum(durations) / len(durations):.1f} 秒（共 {len(durations)} 条有时长）" if durations else "- 时长数据不足",
                f"- 最短 {min(durations):.0f} 秒 / 最长 {max(durations):.0f} 秒" if durations else "",
                f"- 口播总字数：{len(all_text)}，单条平均 {len(all_text) // len(transcripts)} 字"
                if transcripts else "- 没有可统计的口播文稿",
                "",
                "## 三、口播词频（高频词组）",
                "",
                "| 词组 | 出现次数 |",
                "| --- | ---: |",
            ]
        )
        lines.extend(
            [f"| {word} | {count} |" for word, count in frequencies if count >= 2]
        )
        lines.extend(
            [
                "",
                "## 四、跨视频重复话术",
                "",
            ]
        )
        if repeats:
            for item in repeats:
                lines.append(f"- 「{item['phrase']}」出现 {item['count']} 条")
        else:
            lines.append("- 没有发现跨视频重复长句。")
        lines.extend(
            [
                "",
                "## 五、前 40 字钩子",
                "",
            ]
        )
        hook_lines = []
        for entry in ok_entries:
            text = str(entry.get("transcript") or "").strip()
            if text:
                hook_lines.append(f"- {text[:40]}（{entry.get('title') or entry.get('url') or ''}）")
        lines.extend(hook_lines[:60] or ["- 无。"])
        lines.extend(
            [
                "",
                "## 六、促销信号词",
                "",
            ]
        )
        if promotion:
            lines.extend([f"- {word}：{count} 次" for word, count in promotion.most_common(20)])
        else:
            lines.append("- 未检测到促销信号词。")
    lines.extend(
        [
            "",
            "## 七、说明",
            "",
            "- 口播为 AI 转写（本地 whisper / 云端），存在同音字误差，成稿以视频原文为准。",
            f"- 词频统计使用{'jieba 分词' if JIEBA_AVAILABLE else '2 字连续窗口（未安装 jieba，装 jieba 后更准）'}；"
            "重复话术按 6 字滑动窗口跨视频匹配。",
            "- 本报告只做统计呈现，不替代人工判断；需要深入拆解请使用 douyin-video-teardown。",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成短视频提取分析报告。")
    parser.add_argument("input_dir", type=Path, help="extract_video.py 的输出目录")
    parser.add_argument("--out", type=Path, help="报告输出路径，默认 {输入目录}/分析报告.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    entries = load_index(args.input_dir.expanduser().resolve())
    report = build_report(entries)
    out = args.out or args.input_dir / "分析报告.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"报告已生成：{out.resolve()}（基于 {len(entries)} 条记录）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
