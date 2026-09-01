#!/usr/bin/env python3
"""把更新检查真源同步到每个独立 Skill。零第三方依赖。"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "scripts" / "check_update.py.template"


def _skill_dirs() -> list[Path]:
    skills_dir = ROOT / "skills"
    return sorted(path for path in skills_dir.iterdir() if path.is_dir())


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="同步 LJHskill 更新检查器")
    parser.add_argument("--check", action="store_true", help="只检查副本是否与真源一致")
    args = parser.parse_args(argv)

    if not SOURCE.exists():
        print(f"真源不存在：{SOURCE}")
        return 1

    source_hash = _digest(SOURCE)
    problems = []
    for skill_dir in _skill_dirs():
        target = skill_dir / "scripts" / "check_update.py"
        if args.check:
            if not target.exists():
                problems.append(f"{target.relative_to(ROOT)} 不存在")
            elif _digest(target) != source_hash:
                problems.append(f"{target.relative_to(ROOT)} 与真源不一致")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(SOURCE.read_bytes())

    if problems:
        for problem in problems:
            print(problem)
        return 1

    action = "检查" if args.check else "同步"
    print(f"{action}完成：{len(_skill_dirs())} 个 Skill checker 与真源一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
