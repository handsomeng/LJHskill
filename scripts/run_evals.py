#!/usr/bin/env python3
"""LJHskill 行为回归运行器。零第三方依赖（标准库 + subprocess 调 claude CLI）。

工作原理（两段式，每个用例两次 `claude -p` 调用）：

1. 扮演段：读取 skills/{skill}/SKILL.md 全文，安全递归加载它直接引用的本地
   references Markdown，以及 evals/{skill}.json 里该 case 的 scenario。引用文件
   按相对路径放入 prompt；绝对路径、越界、缺失和超限会让该 case 记录 ERROR。

2. 裁判段：把扮演段的输出连同该 case 的 must（语义断言，意思到了就算满足，不要求
   字面匹配）/ must_not（语义禁区，同义表达也算命中）交给第二次 `claude -p` 调用，
   要求只输出一段 JSON 判定结果。

用法：
  python3 scripts/run_evals.py                          # 跑全部 skill 的全部用例
  python3 scripts/run_evals.py --skill ljh-maidian       # 只跑一个 skill
  python3 scripts/run_evals.py --skill ljh-maidian --case chuncengfen-gongxiao-360-maichongtou
  python3 scripts/run_evals.py --jobs 4                  # 并发数

结果同时写 /tmp/ljh_evals_last_run.json（含每个 case 扮演段的完整输出，便于人工复盘）。
任一 case 判定为 FAIL 或 ERROR，退出码为 1。
"""

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = ROOT / "evals"
SKILLS_DIR = ROOT / "skills"
DEFAULT_MODEL = "claude-sonnet-5"
JUDGE_MODEL = "claude-haiku-4-5-20251001"
RESULT_PATH = Path("/tmp/ljh_evals_last_run.json")
TIMEOUT_SECONDS = 300
MAX_REFERENCE_BUNDLE_BYTES = 512 * 1024
MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^)\s]+)")

ROLEPLAY_PROMPT_TEMPLATE = """你要严格按照下面这份 SKILL.md 的指令扮演这个 skill。用户的输入和背景如下。请模拟完整交互（scenario 里给了用户会怎么回答的信息就用它作答），输出这个 skill 最终会给用户的完整回复。

===SKILL.md===
{skill_md}

===本 Skill 本地 references===
{reference_bundle}

===用户输入===
{scenario}"""

JUDGE_PROMPT_TEMPLATE = """你是一个行为回归测试的裁判。下面是某个 skill 针对一个测试用例给出的完整回复，以及这条用例的 must（必须满足项）和 must_not（禁止出现项）。

判定规则：
- must 是语义断言，只要回复里表达的意思达到了这一条的要求就算满足，不要求字面上出现相同的文字。
- must_not 是语义禁区，回复里只要出现了同义或等价的表达就算命中，不要求字面完全一致。

请只输出一段 JSON，不要输出任何其他文字、不要用 markdown 代码块包裹，格式严格如下：
{{"pass": true 或 false, "failed_must": [未满足的 must 原文列表], "hit_must_not": [命中的 must_not 原文列表], "note": "一句话说明判定理由"}}

===待判定的回复===
{output}

===must（必须满足）===
{must}

===must_not（禁止出现）===
{must_not}"""


class ReferenceBundleError(ValueError):
    """本地 Markdown 引用不安全、缺失或超过 bundle 限额。"""


def extract_markdown_links(text):
    """按出现顺序返回 Markdown 链接目标，不解析外部内容。"""
    return [match.group(1) for match in MARKDOWN_LINK_PATTERN.finditer(text)]


def resolve_local_markdown_link(source_path, skill_dir, raw_target, references_only=False):
    """安全解析一个本地 Markdown 链接；外部或非 Markdown 链接返回 None。"""
    source_path = Path(source_path)
    skill_dir = Path(skill_dir).resolve()
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()

    try:
        parsed = urlsplit(target)
    except ValueError as exc:
        raise ReferenceBundleError(f"链接格式无效：{raw_target}") from exc
    if parsed.scheme.lower() in {"http", "https"}:
        return None
    if parsed.scheme or parsed.netloc:
        raise ReferenceBundleError(f"不支持的链接协议：{raw_target}")

    decoded_path = unquote(parsed.path).replace("\\", "/")
    if not decoded_path:
        return None
    if not decoded_path.lower().endswith(".md"):
        return None
    if decoded_path.startswith("/") or re.match(r"^[A-Za-z]:/", decoded_path):
        raise ReferenceBundleError(f"拒绝绝对路径：{raw_target}")

    parts = PurePosixPath(decoded_path).parts
    if ".." in parts:
        raise ReferenceBundleError(f"拒绝 .. 越界路径：{raw_target}")

    source_resolved = source_path.resolve()
    try:
        source_resolved.relative_to(skill_dir)
    except ValueError as exc:
        raise ReferenceBundleError(f"引用来源位于 Skill 目录外：{source_path}") from exc

    unresolved = source_path.parent.joinpath(*parts)
    cursor = source_path.parent
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ReferenceBundleError(f"拒绝符号链接引用：{raw_target}")

    resolved = unresolved.resolve()
    try:
        relative = resolved.relative_to(skill_dir)
    except ValueError as exc:
        raise ReferenceBundleError(f"引用文件位于 Skill 目录外：{raw_target}") from exc

    if references_only and (not relative.parts or relative.parts[0] != "references"):
        return None
    if not resolved.exists():
        raise ReferenceBundleError(f"本地 Markdown 引用不存在：{raw_target}")
    if not resolved.is_file():
        raise ReferenceBundleError(f"本地 Markdown 引用不是文件：{raw_target}")
    return resolved


def load_reference_bundle(skill_md_path, max_total_bytes=MAX_REFERENCE_BUNDLE_BYTES):
    """递归加载 SKILL.md 直接引用的 references，返回 [(相对路径, 内容)]。"""
    skill_md_path = Path(skill_md_path)
    skill_dir = skill_md_path.parent.resolve()
    try:
        skill_text = skill_md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReferenceBundleError(f"SKILL.md 读取失败：{exc}") from exc

    queue = []
    for raw_target in extract_markdown_links(skill_text):
        target = resolve_local_markdown_link(
            skill_md_path,
            skill_dir,
            raw_target,
            references_only=True,
        )
        if target is not None:
            queue.append(target)

    seen = {skill_md_path.resolve()}
    bundle = []
    total_bytes = 0
    while queue:
        path = queue.pop(0)
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            raw = resolved.read_bytes()
            content = raw.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise ReferenceBundleError(f"reference 读取失败：{resolved}: {exc}") from exc

        total_bytes += len(raw)
        if total_bytes > max_total_bytes:
            raise ReferenceBundleError(
                f"reference bundle 超过 {max_total_bytes} 字节上限"
            )

        relative = resolved.relative_to(skill_dir).as_posix()
        bundle.append((relative, content))
        for raw_target in extract_markdown_links(content):
            target = resolve_local_markdown_link(
                resolved,
                skill_dir,
                raw_target,
                references_only=False,
            )
            if target is not None and target not in seen:
                queue.append(target)

    return bundle


def format_reference_bundle(bundle):
    """把 reference bundle 格式化为带相对路径的 prompt 片段。"""
    if not bundle:
        return "（无本地 Markdown reference）"
    sections = []
    for relative, content in bundle:
        sections.append(f"--- {relative} ---\n{content}")
    return "\n\n".join(sections)


def load_cases(skill_filter, case_filter):
    """返回 [(skill_name, case_dict), ...]，按 evals/*.json 文件名排序。"""
    if not EVALS_DIR.is_dir():
        print(f"错误：{EVALS_DIR} 不存在")
        sys.exit(1)

    tasks = []
    eval_files = sorted(EVALS_DIR.glob("*.json"))
    for f in eval_files:
        data = json.loads(f.read_text(encoding="utf-8"))
        skill_name = data.get("skill", f.stem)
        if skill_filter and skill_name != skill_filter:
            continue
        for case in data.get("cases", []):
            if case_filter and case.get("id") != case_filter:
                continue
            tasks.append((skill_name, case))
    return tasks


def call_claude(prompt, model):
    """跑一次 `claude -p --model {model}`，prompt 走 stdin，返回 (成功与否, 输出或错误信息)。"""
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", model],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f"调用超时（{TIMEOUT_SECONDS} 秒）"

    if result.returncode != 0:
        return False, f"claude CLI 返回码 {result.returncode}：{result.stderr.strip()}"

    output = result.stdout.strip()
    if not output:
        return False, f"claude CLI 无输出：{result.stderr.strip()}"

    return True, output


def parse_judge_json(text):
    """从裁判段输出里解析 JSON。允许前后有多余文字或 markdown 代码块包裹。"""
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.S)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        brace_match = re.search(r"(\{.*\})", cleaned, re.S)
        if brace_match:
            cleaned = brace_match.group(1)

    return json.loads(cleaned)


def run_case(skill_name, case, model):
    """跑单个用例的两段式流程，返回结果字典。"""
    case_id = case.get("id", "（无 id）")
    skill_md_path = SKILLS_DIR / skill_name / "SKILL.md"

    record = {
        "skill": skill_name,
        "case_id": case_id,
        "status": "ERROR",
        "note": "",
        "roleplay_output": "",
        "failed_must": [],
        "hit_must_not": [],
    }

    if not skill_md_path.exists():
        record["note"] = f"找不到 {skill_md_path}"
        return record

    try:
        skill_md = skill_md_path.read_text(encoding="utf-8")
        reference_bundle = load_reference_bundle(skill_md_path)
    except (OSError, UnicodeError, ReferenceBundleError) as exc:
        record["note"] = f"reference bundle 加载失败：{exc}"
        return record
    scenario = case.get("scenario", "")

    roleplay_prompt = ROLEPLAY_PROMPT_TEMPLATE.format(
        skill_md=skill_md,
        reference_bundle=format_reference_bundle(reference_bundle),
        scenario=scenario,
    )
    ok, roleplay_output = call_claude(roleplay_prompt, model)
    if not ok:
        record["note"] = f"扮演段调用失败：{roleplay_output}"
        return record

    record["roleplay_output"] = roleplay_output

    must = case.get("must", [])
    must_not = case.get("must_not", [])
    judge_prompt = JUDGE_PROMPT_TEMPLATE.format(
        output=roleplay_output,
        must=json.dumps(must, ensure_ascii=False, indent=2),
        must_not=json.dumps(must_not, ensure_ascii=False, indent=2),
    )

    verdict = None
    last_error = ""
    for attempt in range(2):
        ok, judge_output = call_claude(judge_prompt, JUDGE_MODEL)
        if not ok:
            last_error = f"裁判段调用失败：{judge_output}"
            continue
        try:
            verdict = parse_judge_json(judge_output)
            break
        except (json.JSONDecodeError, AttributeError) as e:
            last_error = f"裁判段输出解析失败（第 {attempt + 1} 次）：{e}；原始输出：{judge_output[:300]}"
            continue

    if verdict is None:
        record["note"] = last_error
        return record

    record["status"] = "PASS" if verdict.get("pass") else "FAIL"
    record["note"] = verdict.get("note", "")
    record["failed_must"] = verdict.get("failed_must", [])
    record["hit_must_not"] = verdict.get("hit_must_not", [])
    return record


def main():
    parser = argparse.ArgumentParser(description="LJHskill 行为回归运行器")
    parser.add_argument("--skill", help="只跑一个 skill 的用例，例如 ljh-maidian；不传则跑全部")
    parser.add_argument("--case", help="只跑指定 case 的 id")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"被测模型，默认 {DEFAULT_MODEL}")
    parser.add_argument("--jobs", type=int, default=2, help="并发数，默认 2")
    args = parser.parse_args()

    tasks = load_cases(args.skill, args.case)
    if not tasks:
        print("没有匹配到任何用例，检查 --skill / --case 参数是否正确")
        sys.exit(1)

    print(f"共 {len(tasks)} 条用例，被测模型 {args.model}，裁判模型 {JUDGE_MODEL}，并发数 {args.jobs}")
    print()

    records = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        future_map = {
            executor.submit(run_case, skill_name, case, args.model): (skill_name, case)
            for skill_name, case in tasks
        }
        for future in as_completed(future_map):
            skill_name, case = future_map[future]
            record = future.result()
            records.append(record)
            print(f"[{record['status']}] {record['skill']} / {record['case_id']}：{record['note']}")

    records.sort(key=lambda r: (r["skill"], r["case_id"]))

    pass_count = sum(1 for r in records if r["status"] == "PASS")
    fail_count = sum(1 for r in records if r["status"] == "FAIL")
    error_count = sum(1 for r in records if r["status"] == "ERROR")

    print()
    print("=" * 60)
    print(f"共 {len(records)} 条：PASS {pass_count}，FAIL {fail_count}，ERROR {error_count}")
    print("=" * 60)

    RESULT_PATH.write_text(
        json.dumps(
            {
                "model": args.model,
                "judge_model": JUDGE_MODEL,
                "results": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"完整结果（含扮演段输出）已写入 {RESULT_PATH}")

    if fail_count or error_count:
        sys.exit(1)


if __name__ == "__main__":
    main()
