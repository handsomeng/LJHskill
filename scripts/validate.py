#!/usr/bin/env python3
"""LJHskill 仓库校验脚本。零依赖，纯标准库。

检查项：
1. skills/*/SKILL.md 存在，frontmatter name 与目录名一致，description 含「触发方式」和「Trigger:」
2. 风格：破折号、「不是……而是……」「而不是」句式零命中
3. 微信仅保留在 README：lijiedelijiea 在所有 skills/*/SKILL.md 中为 0 次、在 README 中恰好 1 次
4. marketplace.json：JSON 合法、skills 路径存在、ljh 主条目覆盖全部 skills、目录数与条目数一致
5. evals/*.json：JSON 合法，符合 schema
6. 敏感词检查：仅当 内部/禁词.txt 存在时才跑，本地专用

用法：python3 scripts/validate.py
任一项 FAIL，退出码为 1。
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

results = []  # (item_name, passed: bool, detail: str)


def report(name, passed, detail=""):
    results.append((name, passed, detail))


def fail_lines(name, lines):
    ok = len(lines) == 0
    detail = "" if ok else "；".join(lines)
    report(name, ok, detail)


# ---------- 1. skills/*/SKILL.md 存在性与 frontmatter ----------

def check_skill_files():
    skills_dir = ROOT / "skills"
    problems = []
    if not skills_dir.is_dir():
        report("1. skills 目录存在", False, "skills/ 目录不存在")
        return []

    skill_dirs = sorted([p for p in skills_dir.iterdir() if p.is_dir()])
    for d in skill_dirs:
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            problems.append(f"{d.name}/SKILL.md 不存在")
            continue
        text = skill_md.read_text(encoding="utf-8")
        m = re.search(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
        if not m:
            problems.append(f"{d.name}/SKILL.md 缺少 frontmatter")
            continue
        frontmatter = m.group(1)
        name_m = re.search(r"^name:\s*(\S+)", frontmatter, re.M)
        if not name_m:
            problems.append(f"{d.name}/SKILL.md frontmatter 缺少 name 字段")
        elif name_m.group(1) != d.name:
            problems.append(f"{d.name}/SKILL.md name 字段 '{name_m.group(1)}' 与目录名不一致")

        if "触发方式" not in frontmatter:
            problems.append(f"{d.name}/SKILL.md description 缺少「触发方式」")
        if "Trigger:" not in frontmatter:
            problems.append(f"{d.name}/SKILL.md description 缺少「Trigger:」")

    fail_lines("1. skills/*/SKILL.md 存在且 frontmatter 合规", problems)
    return skill_dirs


# ---------- 2. 风格检查 ----------

def check_style(md_files):
    problems = []
    dash_pattern = re.compile(r"——|—")
    bushi_pattern = re.compile(r"不是.{0,12}而是")
    erbushi_pattern = re.compile(r"而不是")

    for f in md_files:
        text = f.read_text(encoding="utf-8")
        rel = f.relative_to(ROOT)
        if dash_pattern.search(text):
            problems.append(f"{rel} 命中破折号")
        if bushi_pattern.search(text):
            problems.append(f"{rel} 命中「不是……而是……」句式")
        if erbushi_pattern.search(text):
            problems.append(f"{rel} 命中「而不是」")

    fail_lines("2. 风格：破折号 / 「不是而是」/ 「而不是」零命中", problems)


# ---------- 3. 微信仅保留在 README ----------

def check_wechat(skill_dirs):
    problems = []
    wechat = "lijiedelijiea"

    for d in skill_dirs:
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue
        text = skill_md.read_text(encoding="utf-8")
        count = text.count(wechat)
        if count != 0:
            problems.append(f"{d.name}/SKILL.md 出现 {count} 次，应为 0 次")

    readme = ROOT / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        count = text.count(wechat)
        if count != 1:
            problems.append(f"README.md 出现 {count} 次，应为 1 次")
    else:
        problems.append("README.md 不存在")

    fail_lines("3. 微信仅保留在 README（SKILL.md 均为 0 次，README 恰好 1 次）", problems)


# ---------- 4. marketplace.json ----------

def check_marketplace(skill_dirs):
    problems = []
    mp_path = ROOT / ".claude-plugin" / "marketplace.json"
    if not mp_path.exists():
        report("4. marketplace.json 合法且路径完整", False, "marketplace.json 不存在")
        return

    try:
        data = json.loads(mp_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report("4. marketplace.json 合法且路径完整", False, f"JSON 解析失败：{e}")
        return

    plugins = data.get("plugins", [])
    skill_dir_names = {d.name for d in skill_dirs}

    all_skill_paths = set()
    for plugin in plugins:
        for skill_path in plugin.get("skills", []):
            all_skill_paths.add(skill_path)
            resolved = ROOT / skill_path.lstrip("./")
            if not resolved.is_dir():
                problems.append(f"plugin '{plugin.get('name')}' 引用的路径 {skill_path} 不存在")

    # ljh 主条目要覆盖全部 skills/ 目录
    main_plugin = next((p for p in plugins if p.get("name") == "ljh"), None)
    if main_plugin is None:
        problems.append("找不到名为 ljh 的主条目")
    else:
        main_skill_names = {Path(p).name for p in main_plugin.get("skills", [])}
        missing = skill_dir_names - main_skill_names
        if missing:
            problems.append(f"ljh 主条目未覆盖：{sorted(missing)}")

    # 目录数与条目数一致：plugin 条目总数（含 ljh 主入口，它对应 skills/ljh 这个路由 skill 本身）
    # 应等于 skills/ 目录数
    if len(plugins) != len(skill_dir_names):
        problems.append(
            f"plugin 条目总数 {len(plugins)} 与 skills/ 目录数 {len(skill_dir_names)} 不一致"
        )

    fail_lines("4. marketplace.json JSON 合法、路径完整、目录数与条目数一致", problems)


# ---------- 5. evals/*.json schema ----------

def check_evals(skill_dirs):
    problems = []
    evals_dir = ROOT / "evals"
    if not evals_dir.is_dir():
        report("5. evals/*.json 合法且符合 schema", False, "evals/ 目录不存在")
        return []

    skill_dir_names = {d.name for d in skill_dirs}
    eval_files = sorted(evals_dir.glob("*.json"))
    if not eval_files:
        problems.append("evals/ 目录下没有任何 json 文件")

    for f in eval_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            problems.append(f"{f.name} JSON 解析失败：{e}")
            continue

        skill_field = data.get("skill")
        expected = f.stem
        if skill_field != expected:
            problems.append(f"{f.name} 的 skill 字段 '{skill_field}' 与文件名 '{expected}' 不一致")

        if skill_field not in skill_dir_names:
            problems.append(f"{f.name} 的 skill 字段 '{skill_field}' 在 skills/ 目录下找不到对应目录")

        cases = data.get("cases")
        if not isinstance(cases, list) or len(cases) == 0:
            problems.append(f"{f.name} 缺少非空的 cases 数组")
            continue

        for i, case in enumerate(cases):
            for field in ("id", "scenario", "must", "must_not"):
                if field not in case:
                    problems.append(f"{f.name} 第 {i+1} 个 case 缺少字段 '{field}'")
            if "must" in case and not isinstance(case["must"], list):
                problems.append(f"{f.name} 第 {i+1} 个 case 的 must 字段不是数组")
            if "must_not" in case and not isinstance(case["must_not"], list):
                problems.append(f"{f.name} 第 {i+1} 个 case 的 must_not 字段不是数组")

    fail_lines("5. evals/*.json JSON 合法且符合 schema", problems)
    return eval_files


# ---------- 6. 敏感词检查（本地专用，禁词文件不进 git） ----------

def check_sensitive_words(skill_dirs):
    """脱敏规则针对课程源文件提取出的 SKILL.md 内容，README 的作者署名页不在此列。"""
    banned_path = ROOT / "内部" / "禁词.txt"
    if not banned_path.exists():
        print("跳过敏感词检查（本地禁词文件缺失）")
        return

    words = [w.strip() for w in banned_path.read_text(encoding="utf-8").splitlines() if w.strip()]
    problems = []
    for d in skill_dirs:
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue
        text = skill_md.read_text(encoding="utf-8")
        rel = skill_md.relative_to(ROOT)
        for w in words:
            if w in text:
                problems.append(f"{rel} 命中禁词 '{w}'")

    fail_lines("6. 敏感词检查（本地禁词文件，扫描 skills/*/SKILL.md）", problems)


def public_markdown_files():
    """仓库内会公开的 markdown 文件：所有 SKILL.md + README.md（不含 内部/、CLAUDE.md）。"""
    files = []
    skills_dir = ROOT / "skills"
    if skills_dir.is_dir():
        files.extend(sorted(skills_dir.glob("*/SKILL.md")))
    readme = ROOT / "README.md"
    if readme.exists():
        files.append(readme)
    return files


def main():
    md_files = public_markdown_files()

    skill_dirs = check_skill_files()
    check_style(md_files)
    check_wechat(skill_dirs)
    check_marketplace(skill_dirs)
    check_evals(skill_dirs)
    check_sensitive_words(skill_dirs)

    print()
    print("=" * 60)
    all_pass = True
    for name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name}")
        if not passed and detail:
            for line in detail.split("；"):
                print(f"       - {line}")
        all_pass = all_pass and passed
    print("=" * 60)

    if all_pass:
        print("全部检查通过")
        sys.exit(0)
    else:
        print("存在 FAIL 项")
        sys.exit(1)


if __name__ == "__main__":
    main()
