#!/usr/bin/env python3
"""run_evals 本地 reference bundle loader 的确定性测试，不调用 claude CLI。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_evals


ROOT = Path(__file__).resolve().parent.parent


class ReferenceBundleTests(unittest.TestCase):
    def bundle_paths(self, skill_name: str) -> list[str]:
        skill_md = ROOT / "skills" / skill_name / "SKILL.md"
        return [path for path, _ in run_evals.load_reference_bundle(skill_md)]

    def test_zhibiao_loads_both_references(self):
        paths = self.bundle_paths("ljh-zhibiao")
        self.assertEqual(
            set(paths),
            {"references/metric-trees.md", "references/action-map.md"},
        )
        self.assertEqual(len(paths), 2)

    def test_kaipin_loads_two_chinese_references(self):
        paths = self.bundle_paths("ljh-kaipin")
        self.assertEqual(
            set(paths),
            {
                "references/宏观趋势研究与验证阶段.md",
                "references/竞品素材与微创新.md",
            },
        )

    def test_lianming_loads_case_library(self):
        paths = self.bundle_paths("ljh-lianming")
        self.assertIn("references/lianming-cases.md", paths)
        self.assertIn("references/three-axis-protocol.md", paths)

    def test_skill_without_references_is_valid(self):
        self.assertEqual(self.bundle_paths("ljh-daren"), [])

    def test_recursive_links_are_deduplicated_and_external_links_are_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / "demo"
            references = skill_dir / "references"
            references.mkdir(parents=True)
            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text(
                "[A](references/a.md) [A again](references/a.md) "
                "[Web](https://example.com/doc.md)\n",
                encoding="utf-8",
            )
            (references / "a.md").write_text(
                "[B](b.md) [B again](b.md)\n",
                encoding="utf-8",
            )
            (references / "b.md").write_text("done\n", encoding="utf-8")

            bundle = run_evals.load_reference_bundle(skill_md)
            self.assertEqual(
                [path for path, _ in bundle],
                ["references/a.md", "references/b.md"],
            )

    def test_absolute_and_parent_traversal_are_rejected(self):
        for target in ("/tmp/outside.md", "../outside.md"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp_dir:
                skill_dir = Path(temp_dir) / "demo"
                skill_dir.mkdir()
                skill_md = skill_dir / "SKILL.md"
                skill_md.write_text(f"[bad]({target})\n", encoding="utf-8")
                with self.assertRaises(run_evals.ReferenceBundleError):
                    run_evals.load_reference_bundle(skill_md)

    def test_malformed_link_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / "demo"
            skill_dir.mkdir()
            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text("[bad](https://[invalid/path.md)\n", encoding="utf-8")
            with self.assertRaises(run_evals.ReferenceBundleError):
                run_evals.load_reference_bundle(skill_md)

    def test_missing_local_reference_is_an_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / "demo"
            skill_dir.mkdir()
            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text("[missing](references/missing.md)\n", encoding="utf-8")
            with self.assertRaises(run_evals.ReferenceBundleError):
                run_evals.load_reference_bundle(skill_md)

    def test_symlink_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            skill_dir = temp_root / "demo"
            references = skill_dir / "references"
            references.mkdir(parents=True)
            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text("[outside](references/outside.md)\n", encoding="utf-8")
            outside = temp_root / "outside.md"
            outside.write_text("outside\n", encoding="utf-8")
            (references / "outside.md").symlink_to(outside)

            with self.assertRaises(run_evals.ReferenceBundleError):
                run_evals.load_reference_bundle(skill_md)

    def test_bundle_byte_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / "demo"
            references = skill_dir / "references"
            references.mkdir(parents=True)
            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text("[large](references/large.md)\n", encoding="utf-8")
            (references / "large.md").write_text("0123456789\n", encoding="utf-8")
            with self.assertRaises(run_evals.ReferenceBundleError):
                run_evals.load_reference_bundle(skill_md, max_total_bytes=5)

    def test_reference_error_records_case_error_without_cli_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skills_dir = Path(temp_dir) / "skills"
            skill_dir = skills_dir / "demo"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "[missing](references/missing.md)\n",
                encoding="utf-8",
            )
            case = {"id": "missing-reference", "scenario": "test"}
            with mock.patch.object(run_evals, "SKILLS_DIR", skills_dir), mock.patch.object(
                run_evals,
                "call_claude",
                side_effect=AssertionError("claude CLI must not be called"),
            ) as call_mock:
                record = run_evals.run_case("demo", case, "unused-model")

            self.assertEqual(record["status"], "ERROR")
            self.assertIn("reference bundle 加载失败", record["note"])
            call_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
