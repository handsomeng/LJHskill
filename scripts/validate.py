#!/usr/bin/env python3
"""LJHskill 仓库校验脚本。零依赖，纯标准库。

检查项：
1. skills/*/SKILL.md 存在，frontmatter name 与目录名一致，description 含「触发方式」和「Trigger:」
2. 风格：破折号、「不是……而是……」「而不是」句式零命中
3. 微信检查：lijiedelijiea 在 README 中至少出现 1 次（SKILL.md 中可出现于新手引导）
4. marketplace.json：JSON 合法、业务描述契约和版本一致、skills 路径存在、ljh 主条目覆盖全部 skills，且插件不写显式 version
5. evals/*.json：JSON 合法、符合 schema，并与 skills 一一对应
6. 敏感词检查：仅当 内部/禁词.txt 存在时才跑，本地专用
7. 档案协议齐全性：全部 skills/*/SKILL.md 必须包含「ljh-档案」字样
8. 版本与 Skill 数量
9. 更新检查器副本
10. 三轴协议真源、副本、链接、生产者与消费者契约
11. 交付物字段所有权协议真源、副本、链接与生产消费契约
12. 场景、因子、联名方法契约与关键行为回归
13. 公开文档语言与危险示例边界
14. 行为运行器 reference bundle 与独立包测试契约
15. 活跃旧路由引用

用法：python3 scripts/validate.py
任一项 FAIL，退出码为 1。
"""

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_VERSION = "1.1.0"
EXPECTED_SKILL_COUNT = 20
MAIN_SKILL_NAME = "ljh"
UPDATE_CHECK_SOURCE = ROOT / "scripts" / "check_update.py.template"
UPDATE_CHECK_PROTOCOL = (
    "更新检查：业务交付完成后，环境允许执行时运行本 Skill 目录下的 "
    "`scripts/check_update.py`；脚本有输出时，把提醒原样放在本次业务交付末尾；"
    "无输出不提；不得自动更新。"
)
THREE_AXIS_SOURCE = ROOT / "shared" / "three-axis-protocol.md"
THREE_AXIS_CONSUMERS = (
    "ljh",
    "ljh-brief",
    "ljh-changjing",
    "ljh-dingwei",
    "ljh-duiqi",
    "ljh-jiaoben",
    "ljh-jiazhi",
    "ljh-koc",
    "ljh-lianming",
    "ljh-maidian",
    "ljh-shangxiang",
    "ljh-suanzhang",
    "ljh-xuanpin",
    "ljh-yinzi",
)
THREE_AXIS_REFERENCE = "references/three-axis-protocol.md"
THREE_AXIS_LINK = "开始前读取 [三轴状态协议](references/three-axis-protocol.md)"
EXPECTED_AXIS_VALUES = {
    "一、字段决策状态": {"已确认", "待确认", "修改建议"},
    "二、证据状态": {"已核验", "待核验", "无证据", "已过期", "不适用"},
    "三、验证结果": {"验证通过", "信号偏弱", "验证失败", "未验证"},
}
OWNERSHIP_SOURCE = ROOT / "shared" / "deliverable-field-ownership.md"
OWNERSHIP_CONSUMERS = (
    "ljh",
    "ljh-brief",
    "ljh-dingwei",
    "ljh-duiqi",
    "ljh-jiaoben",
    "ljh-jiazhi",
    "ljh-maidian",
    "ljh-shangxiang",
)
OWNERSHIP_REFERENCE = "references/deliverable-field-ownership.md"
OWNERSHIP_LINK = "[交付物字段所有权协议](references/deliverable-field-ownership.md)"
REQUIRED_CORE_EVAL_CASES = {
    "ljh-xuanpin": {
        "missing-supply-compliance-estimate-blocks-validation",
        "hard-compliance-failure-means-pause",
        "all-gates-pass-enters-validation-without-success-promise",
    },
    "ljh-koc": {
        "organic-seeding-without-attribution-has-no-roi",
        "historical-thresholds-cannot-be-applied-unconditionally",
        "paid-validation-needs-full-design-and-unified-result",
    },
    "ljh-suanzhang": {
        "estimate-mode-cannot-masquerade-as-actual",
        "missing-contribution-costs-must-be-flagged",
        "target-roas-includes-profit-buffer-and-payback",
        "organic-product-card-sales-need-attribution-boundary",
    },
    "ljh-duiqi": {
        "consume-unified-status-without-s-grade",
        "translation-change-is-a-modification-suggestion",
    },
    "ljh-shangxiang": {
        "preserve-three-axis-status-in-page-map",
        "weak-signal-cannot-become-page-promise",
    },
    "ljh": {
        "prelaunch-estimate-routes-to-suanzhang",
        "xuanpin-does-not-promise-unchecked-gates",
    },
}
REQUIRED_OWNERSHIP_EVAL_CASES = {
    "ljh": {
        "main-route-does-not-ask-jiaoben-to-rewrite",
    },
    "ljh-jiazhi": {
        "value-candidate-cannot-become-standard-positioning",
    },
    "ljh-dingwei": {
        "dingwei-requires-xuanpin-enter-validation",
        "value-candidate-remains-candidate-in-dingwei",
        "dingwei-draft-unconfirmed-stays-pending",
        "unverified-story-cannot-enter-standard-positioning",
    },
    "ljh-maidian": {
        "maidian-pass-is-not-compliance-or-market-validation",
        "maidian-cannot-rewrite-standard-positioning",
    },
    "ljh-brief": {
        "brief-no-silent-standard-field-rewrite",
    },
    "ljh-duiqi": {
        "duiqi-no-silent-standard-field-rewrite",
    },
    "ljh-shangxiang": {
        "shangxiang-no-silent-standard-field-rewrite",
    },
    "ljh-jiaoben": {
        "jiaoben-short-format-does-not-require-all-seven",
        "jiaoben-drama-format-can-merge-steps",
        "jiaoben-no-price-anchor-without-credible-reference",
        "jiaoben-does-not-output-full-replacement",
    },
}
REQUIRED_METHOD_EVAL_CASES = {
    "ljh-changjing": {
        "single-item-gmv-is-result-density-not-efficiency",
        "non-comparable-contexts-must-not-be-ranked",
        "single-hit-cannot-prove-scenario",
        "quadrant-is-screening-not-budget-action",
        "thresholds-require-distribution-or-predeclared-rule",
    },
    "ljh-yinzi": {
        "single-hit-cannot-produce-credible-ev-ranking",
        "ev-missing-evidence-has-no-fake-precision",
        "content-factor-grade-is-not-market-validation",
        "controlled-test-required-for-factor-causality",
    },
    "ljh-lianming": {
        "lianming-no-ten-logic-or-fixed-quota",
        "lianming-score-math-boundary",
        "unauthorized-story-cannot-be-candidate-fact",
        "hard-gates-precede-scoring",
    },
    "ljh-qianchuan": {
        "content-factor-grade-does-not-equal-market-validation",
    },
    "ljh": {
        "route-yinzi-single-item-no-ev-ranking",
        "route-lianming-gates-before-kaipin",
        "main-content-factor-grade-not-koc-result",
    },
}
LEGACY_ROUTE = "ljh-" + "li" + "ang" + "ye"
MARKETPLACE_DESCRIPTION_CONTRACTS = {
    "ljh-lianming": ("十种结合逻辑作为候选菜单", "四道硬闸", "可评审候选"),
    "ljh-jiazhi": ("价值候选", "证据缺口", "不生产标准定位"),
    "ljh-xuanpin": ("五个可行性闸门", "进入验证", "补数后再判", "暂缓"),
    "ljh-dingwei": ("选品进入验证后", "标准定位", "标准人群", "心智句"),
    "ljh-maidian": ("独特性", "表达成立性", "证据缺口", "不做合规批准"),
    "ljh-changjing": ("内容投入体量", "销售结果", "结果密度", "四象限只筛选"),
    "ljh-duiqi": ("已确认字段", "翻译", "三轴状态"),
    "ljh-jiaoben": ("平台、目标、时长和格式", "七步诊断镜头", "局部修改方向"),
    "ljh-yinzi": ("单条素材只出因子候选", "多个有依据候选", "EV 区间"),
    "ljh-koc": ("自然种草或寄样", "付费素材或投流", "变量、对照、样本、时间窗和停止条件"),
    "ljh-suanzhang": ("预估和实算双模式", "贡献毛利", "目标 ROAS", "LTV", "最大 CAC"),
    "ljh-shangxiang": ("只编排上游已确认字段", "不升级状态", "不重做定位"),
}
MARKETPLACE_FORBIDDEN_DESCRIPTION_FRAGMENTS = {
    "ljh-lianming": ("十种结合逻辑生成候选方向", "输出联名开品一页纸"),
    "ljh-jiazhi": ("随对话逐步显影",),
    "ljh-xuanpin": ("选品五步判断", "值不值得下场投入打"),
    "ljh-dingwei": ("价值四象限 + 心智句 + 竞争差异",),
    "ljh-maidian": ("盖住成分功效自检",),
    "ljh-changjing": ("画出自己该重投哪个场景",),
    "ljh-duiqi": ("卖点翻译四列表",),
    "ljh-jiaoben": ("指出缺哪步、哪句没配画面",),
    "ljh-yinzi": ("用 EV 公式给专攻课题排优先级",),
    "ljh-koc": ("低成本验证卖点的完整方案",),
    "ljh-suanzhang": ("盈亏平衡 ROI + LTV 实算",),
}
PERFORMATIVE_TERMS = (
    "铁律",
    "硬规则",
    "永远",
    "白拆",
    "劝退",
    "死路",
    "白瞎",
    "薅一把",
    "别偷懒",
    "白聊",
    "死亡螺旋",
    "金钗",
    "颗粒度",
    "抓手",
)
# 若公开文档需要解释禁用词，可在这里按相对路径登记允许出现的词。
# 负向行为回归写在 eval JSON，不进入公开文档扫描范围。
PUBLIC_LANGUAGE_ALLOWLIST = {}
EMPTY_ESSENCE_PATTERNS = (
    re.compile(r"本质上?(?:就是|是)"),
    re.compile(r"这才是.{0,16}本质"),
    re.compile(r"真正(?:的)?本质"),
)
DANGEROUS_EXAMPLE_PATTERNS = (
    re.compile(r"儿童.{0,12}喷"),
    re.compile(r"孩子.{0,12}喷"),
    re.compile(r"旁喷"),
    re.compile(r"不开窗"),
    re.compile(r"关窗.{0,12}喷"),
    re.compile(r"喷手"),
    re.compile(r"手背.{0,12}喷"),
    re.compile(r"名人同款"),
    re.compile(r"明星同款"),
    re.compile(r"贵族"),
    re.compile(r"公爵"),
    re.compile(r"影后"),
    re.compile(r"古老配方"),
    re.compile(r"秘方"),
)
DANGEROUS_EXAMPLE_BOUNDARY_MARKERS = (
    "反例",
    "没有来源",
    "无来源",
    "无证据",
    "待核验",
    "证据缺口",
    "不得",
    "不能",
    "禁止",
)

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
    if len(skill_dirs) != EXPECTED_SKILL_COUNT:
        problems.append(
            f"skills/ 目录数 {len(skill_dirs)}，应为 {EXPECTED_SKILL_COUNT}（19 个业务工具 + 1 个主入口）"
        )
    skill_names = {d.name for d in skill_dirs}
    if MAIN_SKILL_NAME not in skill_names:
        problems.append(f"缺少主入口目录 skills/{MAIN_SKILL_NAME}")
    if len(skill_dirs) - (MAIN_SKILL_NAME in skill_names) != 19:
        problems.append("业务工具目录数应为 19 个")

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

        display_name_m = re.search(r"^displayName:\s*(\S+)", frontmatter, re.M)
        if not display_name_m:
            problems.append(f"{d.name}/SKILL.md frontmatter 缺少 displayName 字段")
        elif display_name_m.group(1) != d.name:
            problems.append(
                f"{d.name}/SKILL.md displayName 字段 '{display_name_m.group(1)}' 与目录名不一致"
            )

        slug_m = re.search(r"^slug:\s*(\S+)", frontmatter, re.M)
        if not slug_m:
            problems.append(f"{d.name}/SKILL.md frontmatter 缺少 slug 字段")
        elif slug_m.group(1) != d.name:
            problems.append(f"{d.name}/SKILL.md slug 字段 '{slug_m.group(1)}' 与目录名不一致")

        version_m = re.search(r"^version:\s*(\S+)", frontmatter, re.M)
        if not version_m:
            problems.append(f"{d.name}/SKILL.md frontmatter 缺少 version 字段")
        elif version_m.group(1) != EXPECTED_VERSION:
            problems.append(
                f"{d.name}/SKILL.md version 为 '{version_m.group(1)}'，应为 '{EXPECTED_VERSION}'"
            )

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


def check_public_language(md_files):
    problems = []
    for path in md_files:
        rel = path.relative_to(ROOT).as_posix()
        allowed_terms = PUBLIC_LANGUAGE_ALLOWLIST.get(rel, set())
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for term in PERFORMATIVE_TERMS:
                if term in line and term not in allowed_terms:
                    problems.append(f"{rel}:{line_no} 命中表演性强硬词 '{term}'")
            for pattern in EMPTY_ESSENCE_PATTERNS:
                if pattern.search(line):
                    problems.append(f"{rel}:{line_no} 命中空泛本质句式 '{pattern.pattern}'")
            if any(pattern.search(line) for pattern in DANGEROUS_EXAMPLE_PATTERNS):
                if not any(marker in line for marker in DANGEROUS_EXAMPLE_BOUNDARY_MARKERS):
                    problems.append(f"{rel}:{line_no} 危险或无来源示例缺少反例/证据边界")

    fail_lines("13. 公开文档语言与危险示例边界", problems)


# ---------- 3. onboarding 与社群信息仅保留在主入口 ----------

def check_onboarding(skill_dirs):
    problems = []
    markers = ("onboarding.json", "用户交流群", "lijiedelijiea", "DamonWang1993")
    main_dir = next((d for d in skill_dirs if d.name == MAIN_SKILL_NAME), None)

    if main_dir is None:
        problems.append("缺少主入口 skills/ljh")
    else:
        main_text = (main_dir / "SKILL.md").read_text(encoding="utf-8")
        for marker in markers:
            if marker not in main_text:
                problems.append(f"skills/ljh/SKILL.md 缺少 '{marker}'")

    for d in skill_dirs:
        if d.name == MAIN_SKILL_NAME:
            continue
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue
        text = skill_md.read_text(encoding="utf-8")
        found = [marker for marker in markers if marker in text]
        if found:
            problems.append(f"{skill_md.relative_to(ROOT)} 含重复 onboarding/社群信息：{found}")

    fail_lines("3. onboarding 与社群信息仅存在于 skills/ljh/SKILL.md", problems)


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

    if not isinstance(data, dict):
        report("4. marketplace.json 合法且路径完整", False, "顶层必须是对象")
        return

    plugins = data.get("plugins", [])
    if not isinstance(plugins, list):
        report("4. marketplace.json 合法且路径完整", False, "plugins 必须是数组")
        return

    skill_dir_names = {d.name for d in skill_dirs}
    plugin_names = set()

    for plugin in plugins:
        if not isinstance(plugin, dict):
            problems.append("marketplace plugins 含非对象条目")
            continue
        plugin_name = plugin.get("name")
        if not isinstance(plugin_name, str) or not plugin_name:
            problems.append("marketplace plugin 缺少有效 name")
            continue
        plugin_names.add(plugin_name)
        description = plugin.get("description")
        if not isinstance(description, str) or not description.strip():
            problems.append(f"plugin '{plugin_name}' 缺少有效 description")
            description = ""
        for fragment in MARKETPLACE_DESCRIPTION_CONTRACTS.get(plugin_name, ()):
            if fragment not in description:
                problems.append(f"plugin '{plugin_name}' description 缺少当前契约：{fragment}")
        for fragment in MARKETPLACE_FORBIDDEN_DESCRIPTION_FRAGMENTS.get(plugin_name, ()):
            if fragment in description:
                problems.append(f"plugin '{plugin_name}' description 命中旧能力：{fragment}")
        if "version" in plugin:
            problems.append(f"plugin '{plugin_name}' 不得包含显式 version")
        skill_paths = plugin.get("skills", [])
        if not isinstance(skill_paths, list):
            problems.append(f"plugin '{plugin_name}' 的 skills 必须是数组")
            continue
        for skill_path in skill_paths:
            if not isinstance(skill_path, str):
                problems.append(f"plugin '{plugin_name}' 含非字符串 skills 路径")
                continue
            resolved = ROOT / skill_path.lstrip("./")
            if not resolved.is_dir():
                problems.append(f"plugin '{plugin.get('name')}' 引用的路径 {skill_path} 不存在")

    missing_plugins = skill_dir_names - plugin_names
    extra_plugins = plugin_names - skill_dir_names
    if missing_plugins:
        problems.append(f"marketplace 缺少插件条目：{sorted(missing_plugins)}")
    if extra_plugins:
        problems.append(f"marketplace 存在未知插件条目：{sorted(extra_plugins)}")

    # ljh 主条目要覆盖全部 skills/ 目录
    main_plugin = next(
        (p for p in plugins if isinstance(p, dict) and p.get("name") == "ljh"),
        None,
    )
    if main_plugin is None:
        problems.append("找不到名为 ljh 的主条目")
    else:
        main_skill_names = {
            Path(p).name for p in main_plugin.get("skills", []) if isinstance(p, str)
        }
        missing = skill_dir_names - main_skill_names
        if missing:
            problems.append(f"ljh 主条目未覆盖：{sorted(missing)}")
        extra = main_skill_names - skill_dir_names
        if extra:
            problems.append(f"ljh 主条目包含未知 skills：{sorted(extra)}")

    # 目录数与条目数一致：plugin 条目总数（含 ljh 主入口，它对应 skills/ljh 这个路由 skill 本身）
    # 应等于 skills/ 目录数
    if len(plugins) != len(skill_dir_names):
        problems.append(
            f"plugin 条目总数 {len(plugins)} 与 skills/ 目录数 {len(skill_dir_names)} 不一致"
        )

    fail_lines("4. marketplace.json 路径、版本与业务描述契约合规", problems)


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

    eval_names = {f.stem for f in eval_files}
    missing_evals = skill_dir_names - eval_names
    extra_evals = eval_names - skill_dir_names
    if missing_evals:
        problems.append(f"skills 缺少对应 eval：{sorted(missing_evals)}")
    if extra_evals:
        problems.append(f"evals 存在无对应 Skill 的文件：{sorted(extra_evals)}")
    if len(eval_files) != len(skill_dirs):
        problems.append(f"eval 文件数 {len(eval_files)} 与 Skill 目录数 {len(skill_dirs)} 不一致")

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


# ---------- 7. 档案协议齐全性 ----------

def check_archive_protocol(skill_dirs):
    problems = []
    for d in skill_dirs:
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue
        text = skill_md.read_text(encoding="utf-8")
        if "ljh-档案" not in text:
            problems.append(f"{d.name}/SKILL.md 缺少「ljh-档案」字样，档案协议未植入")

    fail_lines("7. 档案协议齐全性（全部 SKILL.md 含「ljh-档案」）", problems)


# ---------- 8. 版本一致性、更新检查器与旧路由 ----------

def check_version_consistency(skill_dirs):
    problems = []

    release_path = ROOT / "release.json"
    if not release_path.exists():
        problems.append("release.json 不存在")
    else:
        try:
            release = json.loads(release_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as e:
            problems.append(f"release.json 读取或解析失败：{e}")
        else:
            if not isinstance(release, dict):
                problems.append("release.json 顶层必须是对象")
            else:
                if release.get("version") != EXPECTED_VERSION:
                    problems.append(
                        f"release.json version 为 '{release.get('version')}'，应为 '{EXPECTED_VERSION}'"
                    )
                if release.get("suite_version") != EXPECTED_VERSION:
                    problems.append(
                        f"release.json suite_version 为 '{release.get('suite_version')}'，应为 '{EXPECTED_VERSION}'"
                    )
                for field in (
                    "released_at",
                    "summary",
                    "readme_url",
                    "update_instructions_url",
                    "readme_update_entry",
                ):
                    if not release.get(field):
                        problems.append(f"release.json 缺少 {field} 字段")

    readme_path = ROOT / "README.md"
    if not readme_path.exists():
        problems.append("README.md 不存在")
    else:
        readme_text = readme_path.read_text(encoding="utf-8")
        readme_version = re.search(r"\*\*最新版本 v([^*]+)\*\*", readme_text)
        if not readme_version:
            problems.append("README.md 缺少最新版本标记")
        elif readme_version.group(1) != EXPECTED_VERSION:
            problems.append(
                f"README.md 最新版本为 '{readme_version.group(1)}'，应为 '{EXPECTED_VERSION}'"
            )
        for snippet in (
            "## 如何更新",
            "claude plugin update ljh@ljhskill",
            "npx -y skills add handsomeng/LJHskill -g --all",
        ):
            if snippet not in readme_text:
                problems.append(f"README.md 缺少更新说明：{snippet}")

    marketplace_path = ROOT / ".claude-plugin" / "marketplace.json"
    if marketplace_path.exists():
        try:
            marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as e:
            problems.append(f"marketplace.json 读取或解析失败：{e}")
        else:
            metadata = marketplace.get("metadata") if isinstance(marketplace, dict) else None
            if not isinstance(metadata, dict) or metadata.get("version") != EXPECTED_VERSION:
                actual = metadata.get("version") if isinstance(metadata, dict) else None
                problems.append(
                    f"marketplace metadata.version 为 '{actual}'，应为 '{EXPECTED_VERSION}'"
                )

    fail_lines("8. README、release.json、frontmatter 与 marketplace 版本一致", problems)


def check_update_checkers(skill_dirs):
    problems = []
    if not UPDATE_CHECK_SOURCE.exists():
        report("9. 每个 Skill 的更新检查器与真源一致", False, "更新检查真源不存在")
        return

    source_hash = hashlib.sha256(UPDATE_CHECK_SOURCE.read_bytes()).hexdigest()
    for d in skill_dirs:
        checker = d / "scripts" / "check_update.py"
        if not checker.exists():
            problems.append(f"{checker.relative_to(ROOT)} 不存在")
            continue
        checker_hash = hashlib.sha256(checker.read_bytes()).hexdigest()
        if checker_hash != source_hash:
            problems.append(f"{checker.relative_to(ROOT)} 与真源哈希不一致")
        skill_md = d / "SKILL.md"
        if skill_md.exists() and UPDATE_CHECK_PROTOCOL not in skill_md.read_text(encoding="utf-8"):
            problems.append(f"{skill_md.relative_to(ROOT)} 缺少完整更新检查协议")

    fail_lines("9. 每个 Skill 的更新检查器与调用协议一致", problems)


def _extract_protocol_axis(source_text, heading):
    match = re.search(
        rf"^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)",
        source_text,
        re.M | re.S,
    )
    if not match:
        return None

    values = set()
    for line in match.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        if first in {"状态", "结果"}:
            continue
        if first and set(first) <= {"-", ":"}:
            continue
        if first:
            values.add(first)
    return values


def check_three_axis_protocol(skill_dirs):
    problems = []
    sync_script = ROOT / "scripts" / "sync_three_axis_protocol.py"
    if not sync_script.exists():
        problems.append("scripts/sync_three_axis_protocol.py 不存在")

    if not THREE_AXIS_SOURCE.exists():
        report("10. 三轴协议副本、链接与核心契约", False, "三轴协议真源不存在")
        return

    source_bytes = THREE_AXIS_SOURCE.read_bytes()
    source_text = source_bytes.decode("utf-8")
    source_hash = hashlib.sha256(source_bytes).hexdigest()

    for heading, expected in EXPECTED_AXIS_VALUES.items():
        actual = _extract_protocol_axis(source_text, heading)
        if actual is None:
            problems.append(f"三轴协议缺少章节「{heading}」")
        elif actual != expected:
            problems.append(
                f"三轴协议「{heading}」枚举为 {sorted(actual)}，应为 {sorted(expected)}"
            )

    skill_names = {d.name for d in skill_dirs}
    missing_consumers = set(THREE_AXIS_CONSUMERS) - skill_names
    if missing_consumers:
        problems.append(f"三轴协议消费者目录缺失：{sorted(missing_consumers)}")

    for skill_name in THREE_AXIS_CONSUMERS:
        skill_dir = ROOT / "skills" / skill_name
        reference = skill_dir / THREE_AXIS_REFERENCE
        skill_md = skill_dir / "SKILL.md"
        if not reference.exists():
            problems.append(f"{reference.relative_to(ROOT)} 不存在")
        elif hashlib.sha256(reference.read_bytes()).hexdigest() != source_hash:
            problems.append(f"{reference.relative_to(ROOT)} 与真源哈希不一致")
        if not skill_md.exists():
            continue
        text = skill_md.read_text(encoding="utf-8")
        if THREE_AXIS_LINK not in text:
            problems.append(f"{skill_md.relative_to(ROOT)} 缺少三轴协议读取链接")

    for skill_dir in skill_dirs:
        if skill_dir.name in THREE_AXIS_CONSUMERS:
            continue
        unexpected = skill_dir / THREE_AXIS_REFERENCE
        if unexpected.exists():
            problems.append(f"{unexpected.relative_to(ROOT)} 不应复制无关三轴协议")

    required_contracts = {
        "ljh-xuanpin": (
            "结论只用三种：**进入验证、补数后再判、暂缓**",
            "### 闸门一：需求机会",
            "### 闸门二：产品交付",
            "### 闸门三：合规",
            "### 闸门四：供应链",
            "### 闸门五：预估贡献毛利",
            "| 五个闸门全部为「闸门已过」 | 进入验证 | 未验证 |",
            "| 任一硬闸为「闸门未过」 | 暂缓 | 未验证 |",
        ),
        "ljh-koc": (
            "### A 模式：自然种草或寄样验证",
            "### B 模式：付费素材或投流验证",
            "没有可归因广告消耗与净成交 GMV 时，不输出 ROI 或 ROAS",
            "自变量、控制变量、对照、时间窗、样本单位、异常账号处理和四类停止条件",
            "结果只用：**验证通过、信号偏弱、验证失败、未验证**",
            "高消耗素材只说明平台愿意继续分发或该素材能承接预算，不能单独证明精准人群",
        ),
        "ljh-suanzhang": (
            "| 预估模式 | 开品、选品或投放前 |",
            "| 实算模式 | 已有净成交、消耗、退款和成本数据 |",
            "广告前贡献毛利率 = 广告前贡献毛利 ÷ 订单净收入",
            "只有以下口径同时成立时，公式才能使用",
            "目标投放 ROAS",
            "获客前生命周期贡献",
            "扣 CAC 后生命周期净贡献",
            "不能自动全算成广告外溢",
        ),
        "ljh-duiqi": (
            "标准定位、标准人群和心智句只能来自 `/ljh-dingwei` 的已确认版本",
            "任何内容改写先标「修改建议」",
            "| 产品或上游原话 | 消费者表达 | 可拍画面或演示 | 字段决策状态 | 证据状态 | 验证结果 | 来源 |",
            "证据状态和验证结果原样传递",
        ),
        "ljh-shangxiang": (
            "页面只消费上游状态",
            "字段决策状态、证据状态和验证结果原样保留",
            "只沿用「验证通过、信号偏弱、验证失败、未验证」",
        ),
        "ljh": (
            "开品原点 → 可行性闸门（需求、交付、合规、供应链、预估账）→ 价值与定位 → 场景与内容假设 → KOC 或素材验证 → 执行与放大 → 实际总账与复盘",
            "`/ljh-suanzhang` 预估模式",
            "`/ljh-suanzhang` 实算模式",
            "主入口只路由和传递",
        ),
    }

    for skill_name, fragments in required_contracts.items():
        skill_md = ROOT / "skills" / skill_name / "SKILL.md"
        if not skill_md.exists():
            continue
        text = skill_md.read_text(encoding="utf-8")
        for fragment in fragments:
            if fragment not in text:
                problems.append(f"{skill_md.relative_to(ROOT)} 缺少核心契约：{fragment}")

    old_status_patterns = {
        "ljh-xuanpin": (r"\{打 / 不打", r"判定「打」", r"结论为「打」"),
        "ljh-koc": (r"S\s*级", r"弱信号（待复验）", r"初步观察", r"❌不过"),
        "ljh-duiqi": (r"S\s*级", r"测试中", r"初步观察", r"待复验"),
        "ljh-shangxiang": (r"S\s*级", r"测试中", r"初步观察", r"待复验"),
    }
    for skill_name, patterns in old_status_patterns.items():
        skill_md = ROOT / "skills" / skill_name / "SKILL.md"
        if not skill_md.exists():
            continue
        text = skill_md.read_text(encoding="utf-8")
        for pattern in patterns:
            if re.search(pattern, text):
                problems.append(f"{skill_md.relative_to(ROOT)} 命中旧状态模式：{pattern}")

    for skill_name, required_ids in REQUIRED_CORE_EVAL_CASES.items():
        eval_path = ROOT / "evals" / f"{skill_name}.json"
        if not eval_path.exists():
            continue
        try:
            data = json.loads(eval_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        actual_ids = {
            case.get("id")
            for case in data.get("cases", [])
            if isinstance(case, dict) and isinstance(case.get("id"), str)
        }
        missing_ids = required_ids - actual_ids
        if missing_ids:
            problems.append(f"{eval_path.relative_to(ROOT)} 缺少核心回归：{sorted(missing_ids)}")

    fail_lines("10. 三轴协议副本、链接与核心生产消费契约", problems)


def check_field_ownership_protocol(skill_dirs):
    problems = []
    sync_script = ROOT / "scripts" / "sync_field_ownership_protocol.py"
    if not sync_script.exists():
        problems.append("scripts/sync_field_ownership_protocol.py 不存在")

    if not OWNERSHIP_SOURCE.exists():
        report("11. 字段所有权协议副本、链接与生产消费契约", False, "字段所有权协议真源不存在")
        return

    source_bytes = OWNERSHIP_SOURCE.read_bytes()
    source_text = source_bytes.decode("utf-8")
    source_hash = hashlib.sha256(source_bytes).hexdigest()

    source_owners = set(re.findall(r"^\| `/(ljh[^`]*)` \|", source_text, re.M))
    expected_owners = set(OWNERSHIP_CONSUMERS)
    if source_owners != expected_owners:
        problems.append(
            f"字段所有权表 Skill 为 {sorted(source_owners)}，应为 {sorted(expected_owners)}"
        )

    source_contracts = (
        "标准定位、标准人群和心智句",
        "修改建议",
        "理由",
        "回退所有者",
        "确认动作",
        "卖点评审通过，只代表本轮独特性和表达检验通过",
        "不代表市场验证通过或合规批准",
    )
    for fragment in source_contracts:
        if fragment not in source_text:
            problems.append(f"字段所有权真源缺少协议项：{fragment}")

    skill_names = {d.name for d in skill_dirs}
    missing_consumers = expected_owners - skill_names
    if missing_consumers:
        problems.append(f"字段所有权消费者目录缺失：{sorted(missing_consumers)}")

    for skill_name in OWNERSHIP_CONSUMERS:
        skill_dir = ROOT / "skills" / skill_name
        reference = skill_dir / OWNERSHIP_REFERENCE
        skill_md = skill_dir / "SKILL.md"
        if not reference.exists():
            problems.append(f"{reference.relative_to(ROOT)} 不存在")
        elif hashlib.sha256(reference.read_bytes()).hexdigest() != source_hash:
            problems.append(f"{reference.relative_to(ROOT)} 与真源哈希不一致")
        if skill_md.exists() and OWNERSHIP_LINK not in skill_md.read_text(encoding="utf-8"):
            problems.append(f"{skill_md.relative_to(ROOT)} 缺少字段所有权协议读取链接")

    for skill_dir in skill_dirs:
        if skill_dir.name in OWNERSHIP_CONSUMERS:
            continue
        unexpected = skill_dir / OWNERSHIP_REFERENCE
        if unexpected.exists():
            problems.append(f"{unexpected.relative_to(ROOT)} 不应复制无关字段所有权协议")

    producer_consumer_contracts = {
        "ljh-jiazhi": (
            "只生产价值候选与证据缺口，不生产最终定位",
            "候选不能直接升级成标准字段",
        ),
        "ljh-dingwei": (
            "只有 `/ljh-xuanpin` 已给出「进入验证」时",
            "负责产出并维护三个标准字段：标准定位、标准人群、心智句",
            "只有明确确认后",
        ),
        "ljh-maidian": (
            "只判断卖点或主张的独特性、表达成立性和证据缺口",
            "不代表市场验证通过，也不代表合规批准或资质有效",
            "回退所有者：/ljh-dingwei",
        ),
        "ljh-duiqi": (
            "不重新推导标准定位、标准人群或卖点",
            "修改建议 + 理由 + 回退所有者 + 确认动作",
        ),
        "ljh-brief": (
            "不重新推导标准定位、标准人群或卖点",
            "下游工具只能使用 Brief 中标为「已确认」的字段",
            "回退所有者",
        ),
        "ljh-shangxiang": (
            "只负责页面组织，不重新推导标准定位、标准人群或卖点",
            "页面化改写没有升级证据或验证状态，也没有静默覆盖标准字段",
        ),
        "ljh-jiaoben": (
            "不替创作者自动生成整篇高转化脚本",
            "不要求每条内容机械集齐七步",
            "价格锚只在真实价格阻力和可信参照同时存在时使用",
        ),
        "ljh": (
            "主入口只路由和传递",
            "`/ljh-jiaoben` 不输出整篇替代稿",
        ),
    }
    for skill_name, fragments in producer_consumer_contracts.items():
        skill_md = ROOT / "skills" / skill_name / "SKILL.md"
        if not skill_md.exists():
            continue
        text = skill_md.read_text(encoding="utf-8")
        for fragment in fragments:
            if fragment not in text:
                problems.append(f"{skill_md.relative_to(ROOT)} 缺少所有权契约：{fragment}")

    forbidden_contracts = {
        "ljh-dingwei": ("一个新品立项，第一件事", "直接复用已通过体检的心智句"),
        "ljh-maidian": ("判「打回」", "合规免责"),
        "ljh-jiaoben": ("七步齐全度", "每一句话术", "内核 3 分"),
        "ljh": ("回 `/ljh-jiaoben` 重新写脚本",),
    }
    for skill_name, fragments in forbidden_contracts.items():
        skill_md = ROOT / "skills" / skill_name / "SKILL.md"
        if not skill_md.exists():
            continue
        text = skill_md.read_text(encoding="utf-8")
        for fragment in fragments:
            if fragment in text:
                problems.append(f"{skill_md.relative_to(ROOT)} 命中旧所有权契约：{fragment}")

    for skill_name, required_ids in REQUIRED_OWNERSHIP_EVAL_CASES.items():
        eval_path = ROOT / "evals" / f"{skill_name}.json"
        if not eval_path.exists():
            continue
        try:
            data = json.loads(eval_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        actual_ids = {
            case.get("id")
            for case in data.get("cases", [])
            if isinstance(case, dict) and isinstance(case.get("id"), str)
        }
        missing_ids = required_ids - actual_ids
        if missing_ids:
            problems.append(f"{eval_path.relative_to(ROOT)} 缺少所有权回归：{sorted(missing_ids)}")

    fail_lines("11. 字段所有权协议副本、链接与生产消费契约", problems)


def check_scenario_factor_collab_contracts():
    problems = []
    required_contracts = {
        "ljh-changjing": (
            "原点场景，是用户最先产生强需求、最值得先打透的具体使用时刻",
            "| 素材条数和占比 | 内容投入体量 |",
            "| GMV 和占比 | 观察到的销售结果 |",
            "| 单条 GMV | 同口径素材的结果密度 |",
            "没有投放消耗、曝光、制作成本或时间等分母时，不能把单条 GMV 称为效率",
            "四象限只用于机会筛选",
            "不得默认使用无来源平均值、固定条数占比或固定样本阈值",
            "单条爆款需要单列离群点分析，不能证明整个场景有效",
            "字段决策状态 | 证据状态 | 验证结果 | 最小验证动作",
        ),
        "ljh-yinzi": (
            "用于比较候选方向的粗略预期价值辅助值",
            "单条素材只能产出因子候选、观察和可测试方向",
            "EV 排序至少需要两个候选方向",
            "不计算可信 EV 排名",
            "EV = 价值 × 胜率 ÷ 成本",
            "区间明显重叠时写「并列」或「信息不足」",
            "统一称为「内容因子等级」",
            "内容因子等级不能写成三轴协议中的「验证通过」",
            "因果归因需要控制变量、对照、时间窗、样本和复现",
            "单条素材因子拆解表",
            "横向因子对比表",
        ),
        "ljh-lianming": (
            "十种结合逻辑是候选生成菜单，也是漏项检查清单",
            "它不要求每一种都产出方向",
            "候选数量由可用元素、方向差异度、授权可行性和用户决策需要决定",
            "| 品牌与人群相关 |",
            "| 产品和场景成立 |",
            "| 授权与合规可行 |",
            "| 供应与预估账可行 |",
            "每项 1 到 3 分，总分范围为 3 到 9 分",
            "没有授权时不能写成候选事实或对外联名故事",
            "任一硬闸未过，候选不能进入 `/ljh-kaipin`",
            "预估贡献毛利缺失时转 `/ljh-suanzhang` 预估模式",
        ),
        "ljh-qianchuan": (
            "内容因子等级是 `/ljh-yinzi` 对本轮内容测试表现使用的 S、A、B 标签",
            "不能据此宣布市场验证通过",
        ),
        "ljh": (
            "单条只产因子候选；EV 比较需要至少两个有依据方向",
            "内容因子等级不能替代产品、卖点、人群或市场验证",
            "四道硬闸全部通过，用户圈定方向",
        ),
    }
    for skill_name, fragments in required_contracts.items():
        path = ROOT / "skills" / skill_name / "SKILL.md"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for fragment in fragments:
            if fragment not in text:
                problems.append(f"{path.relative_to(ROOT)} 缺少方法契约：{fragment}")

    forbidden_literals = {
        "ljh-changjing": (
            "单条 GMV 是**效率**",
            "条数占比 20%",
            "重投，主战场",
            "条数少于 20 条",
            "全场景的平均单条 GMV",
        ),
        "ljh-yinzi": (
            "金钗",
            "价值（1-10 分）",
            "按保守值打分",
            "每个专攻至少拉 50 条样本",
            "状态分 S 级",
        ),
        "ljh-lianming": (
            "每条至少逼出 1 个候选",
            "候选方向池（10 到 15 个）",
            "占 0 项（≤2 分）",
            "优选 TOP 3",
            "每个项目至少逼 1 个进阶候选",
        ),
        "ljh-qianchuan": (
            "拿已经验证过的 S 级素材",
            "拿已验证的 S 级素材",
        ),
        "ljh": (
            "测出了跑赢的顶级因子，做完 EV 排序",
            "联名候选池产出，用户圈定方向",
        ),
    }
    for skill_name, fragments in forbidden_literals.items():
        path = ROOT / "skills" / skill_name / "SKILL.md"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for fragment in fragments:
            if fragment in text:
                problems.append(f"{path.relative_to(ROOT)} 命中旧方法：{fragment}")

    for skill_name, required_ids in REQUIRED_METHOD_EVAL_CASES.items():
        eval_path = ROOT / "evals" / f"{skill_name}.json"
        if not eval_path.exists():
            problems.append(f"{eval_path.relative_to(ROOT)} 不存在")
            continue
        try:
            data = json.loads(eval_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        actual_ids = {
            case.get("id")
            for case in data.get("cases", [])
            if isinstance(case, dict) and isinstance(case.get("id"), str)
        }
        missing_ids = required_ids - actual_ids
        if missing_ids:
            problems.append(f"{eval_path.relative_to(ROOT)} 缺少方法回归：{sorted(missing_ids)}")

    fail_lines("12. 场景、因子、联名方法契约与关键行为回归", problems)


def check_behavior_runner_and_package_tests():
    problems = []
    runner_path = ROOT / "scripts" / "run_evals.py"
    runner_test_path = ROOT / "scripts" / "test_run_evals.py"
    package_test_path = ROOT / "scripts" / "test_skill_packages.py"

    for path in (runner_path, runner_test_path, package_test_path):
        if not path.is_file():
            problems.append(f"{path.relative_to(ROOT)} 不存在")

    if runner_path.is_file():
        runner_text = runner_path.read_text(encoding="utf-8")
        runner_contracts = (
            "MAX_REFERENCE_BUNDLE_BYTES",
            "def extract_markdown_links",
            "def resolve_local_markdown_link",
            "references_only=True",
            "if cursor.is_symlink()",
            "def load_reference_bundle",
            "total_bytes > max_total_bytes",
            "reference_bundle=format_reference_bundle(reference_bundle)",
            "reference bundle 加载失败",
        )
        for fragment in runner_contracts:
            if fragment not in runner_text:
                problems.append(f"scripts/run_evals.py 缺少 bundle loader 契约：{fragment}")

    if runner_test_path.is_file():
        test_text = runner_test_path.read_text(encoding="utf-8")
        required_tests = (
            "test_zhibiao_loads_both_references",
            "test_kaipin_loads_two_chinese_references",
            "test_lianming_loads_case_library",
            "test_skill_without_references_is_valid",
            "test_recursive_links_are_deduplicated_and_external_links_are_skipped",
            "test_absolute_and_parent_traversal_are_rejected",
            "test_malformed_link_is_rejected",
            "test_missing_local_reference_is_an_error",
            "test_symlink_reference_is_rejected",
            "test_reference_error_records_case_error_without_cli_call",
        )
        for fragment in required_tests:
            if fragment not in test_text:
                problems.append(f"scripts/test_run_evals.py 缺少确定性测试：{fragment}")

    if package_test_path.is_file():
        package_test_text = package_test_path.read_text(encoding="utf-8")
        package_contracts = (
            "EXPECTED_SKILL_COUNT = 20",
            "shutil.copytree",
            "rglob(\"*.md\")",
            "resolve_local_markdown_link",
            "py_compile.compile",
        )
        for fragment in package_contracts:
            if fragment not in package_test_text:
                problems.append(f"scripts/test_skill_packages.py 缺少独立包契约：{fragment}")

    fail_lines("14. 行为运行器安全加载 references 且独立包测试存在", problems)


def check_active_old_route():
    problems = []
    readme_path = ROOT / "README.md"
    migration_heading = "## v0.9.1 迁移说明"

    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if LEGACY_ROUTE in path.name:
            problems.append(f"文件名仍含旧路由：{path.relative_to(ROOT)}")
        if path.name == "AGENTS.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if LEGACY_ROUTE not in text:
            continue
        if path == readme_path and migration_heading in text:
            before_migration = text.split(migration_heading, 1)[0]
            if LEGACY_ROUTE not in before_migration:
                continue
        problems.append(f"活跃文件仍含旧路由：{path.relative_to(ROOT)}")

    if not readme_path.exists() or migration_heading not in readme_path.read_text(encoding="utf-8"):
        problems.append("README.md 缺少 v0.9.1 迁移说明")

    fail_lines("15. 活跃文件无旧主播工具路由残留", problems)


def public_markdown_files():
    """仓库公开 Markdown：README、SKILL.md 与各 Skill 的 references。"""
    files = []
    skills_dir = ROOT / "skills"
    if skills_dir.is_dir():
        files.extend(sorted(skills_dir.glob("*/SKILL.md")))
        files.extend(sorted(skills_dir.glob("*/references/*.md")))
    readme = ROOT / "README.md"
    if readme.exists():
        files.append(readme)
    return files


def main():
    md_files = public_markdown_files()

    skill_dirs = check_skill_files()
    check_style(md_files)
    check_onboarding(skill_dirs)
    check_marketplace(skill_dirs)
    check_evals(skill_dirs)
    check_sensitive_words(skill_dirs)
    check_archive_protocol(skill_dirs)
    check_version_consistency(skill_dirs)
    check_update_checkers(skill_dirs)
    check_three_axis_protocol(skill_dirs)
    check_field_ownership_protocol(skill_dirs)
    check_scenario_factor_collab_contracts()
    check_public_language(md_files)
    check_behavior_runner_and_package_tests()
    check_active_old_route()

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
