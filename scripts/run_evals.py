#!/usr/bin/env python3
"""LJHskill 行为回归运行器。零第三方依赖（标准库 + subprocess 调 claude CLI）。

工作原理（两段式，每个用例两次 `claude -p` 调用）：

1. 扮演段：读取 skills/{skill}/SKILL.md 全文和 evals/{skill}.json 里该 case 的
   scenario，拼一个 prompt 让被测模型严格按 SKILL.md 的指令扮演这个 skill，模拟
   完整交互并输出最终回复给用户的内容。

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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = ROOT / "evals"
SKILLS_DIR = ROOT / "skills"
DEFAULT_MODEL = "claude-sonnet-5"
JUDGE_MODEL = "claude-haiku-4-5-20251001"
RESULT_PATH = Path("/tmp/ljh_evals_last_run.json")
TIMEOUT_SECONDS = 300

ROLEPLAY_PROMPT_TEMPLATE = """你要严格按照下面这份 SKILL.md 的指令扮演这个 skill。用户的输入和背景如下。请模拟完整交互（scenario 里给了用户会怎么回答的信息就用它作答），输出这个 skill 最终会给用户的完整回复。

===SKILL.md===
{skill_md}

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
        brace_match = re.search(r"\{.*\}", cleaned, re.S)
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

    skill_md = skill_md_path.read_text(encoding="utf-8")
    scenario = case.get("scenario", "")

    roleplay_prompt = ROLEPLAY_PROMPT_TEMPLATE.format(skill_md=skill_md, scenario=scenario)
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
