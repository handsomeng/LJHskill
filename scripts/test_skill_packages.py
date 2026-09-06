#!/usr/bin/env python3
"""19 个独立 Skill 的自包含冒烟测试。零第三方依赖，不访问网络。"""

from __future__ import annotations

import py_compile
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import run_evals


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
EXPECTED_SKILL_COUNT = 20


def frontmatter_name(skill_md: Path) -> str | None:
    """读取 frontmatter 的 name 字段。"""
    text = skill_md.read_text(encoding="utf-8")
    frontmatter = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not frontmatter:
        return None
    name = re.search(r"^name:\s*(\S+)\s*$", frontmatter.group(1), re.M)
    return name.group(1) if name else None


class StandaloneSkillPackageTests(unittest.TestCase):
    def test_all_skill_packages_are_self_contained(self):
        skill_dirs = sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir())
        self.assertEqual(EXPECTED_SKILL_COUNT, len(skill_dirs))

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            for source_dir in skill_dirs:
                with self.subTest(skill=source_dir.name):
                    package_dir = temp_root / source_dir.name
                    shutil.copytree(source_dir, package_dir, symlinks=True)

                    skill_md = package_dir / "SKILL.md"
                    self.assertTrue(skill_md.is_file(), f"{source_dir.name} 缺少 SKILL.md")
                    self.assertEqual(source_dir.name, frontmatter_name(skill_md))

                    for markdown_file in sorted(package_dir.rglob("*.md")):
                        text = markdown_file.read_text(encoding="utf-8")
                        for raw_target in run_evals.extract_markdown_links(text):
                            run_evals.resolve_local_markdown_link(
                                markdown_file,
                                package_dir,
                                raw_target,
                                references_only=False,
                            )

                    checker = package_dir / "scripts" / "check_update.py"
                    self.assertTrue(
                        checker.is_file(),
                        f"{source_dir.name} 缺少 scripts/check_update.py",
                    )
                    cache_file = temp_root / f"{source_dir.name}-check-update.pyc"
                    py_compile.compile(
                        str(checker),
                        cfile=str(cache_file),
                        doraise=True,
                    )


if __name__ == "__main__":
    unittest.main()
