"""自动发版脚本单元测试

@Author: 花海
@Date: 2026/08/17 22:00
@Description: 覆盖 scripts/release_after_merge.py 的正式版本计算规则
              （dev→main 合入发版：剥离 .devN + 按 PR 标题前缀递增）与 PR 标题解析集成。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from release_after_merge import release_version  # noqa: E402
from version_bump import CommitType, parse_commit_type  # noqa: E402


class TestReleaseVersion:
    """正式版本计算规则（main 合入发版）。"""

    def test_dev_feat_bumps_minor(self) -> None:
        assert release_version("0.1.0.dev5", CommitType.FEAT) == "0.2.0"

    def test_dev_patch_bumps_patch(self) -> None:
        assert release_version("0.1.0.dev5", CommitType.PATCH) == "0.1.1"

    def test_dev_breaking_bumps_major(self) -> None:
        assert release_version("0.1.0.dev5", CommitType.BREAKING) == "1.0.0"

    def test_dev_docs_strip_only(self) -> None:
        # docs/chore 合入：仅剥离 .devN 正式化，不递增
        assert release_version("0.1.0.dev5", CommitType.NO_CHANGE) == "0.1.0"

    def test_no_dev_feat_bumps_minor(self) -> None:
        assert release_version("0.1.0", CommitType.FEAT) == "0.2.0"

    def test_no_dev_patch_bumps_patch(self) -> None:
        assert release_version("0.1.0", CommitType.PATCH) == "0.1.1"

    def test_no_dev_breaking_bumps_major(self) -> None:
        assert release_version("2.9.9", CommitType.BREAKING) == "3.0.0"

    def test_no_dev_docs_returns_none(self) -> None:
        # 无 .devN 时 docs/chore 不更新版本
        assert release_version("0.1.0", CommitType.NO_CHANGE) is None

    def test_skip_returns_none(self) -> None:
        assert release_version("0.1.0.dev3", CommitType.SKIP) is None

    def test_minor_carry(self) -> None:
        assert release_version("0.9.9", CommitType.FEAT) == "0.10.0"

    def test_invalid_version_raises(self) -> None:
        with pytest.raises(ValueError):
            release_version("abc", CommitType.FEAT)


class TestReleaseFromPrTitle:
    """PR 标题 → 正式版本集成。"""

    def test_feat_pr_title(self) -> None:
        commit_type = parse_commit_type("feat: 新增订单能力")
        assert release_version("0.1.0.dev5", commit_type) == "0.2.0"

    def test_fix_pr_title(self) -> None:
        commit_type = parse_commit_type("fix: 修复并发问题")
        assert release_version("0.1.0.dev5", commit_type) == "0.1.1"

    def test_breaking_pr_title(self) -> None:
        commit_type = parse_commit_type("feat!: 破坏性重构")
        assert release_version("0.1.0.dev5", commit_type) == "1.0.0"

    def test_docs_pr_title(self) -> None:
        commit_type = parse_commit_type("docs: 更新说明文档")
        assert release_version("0.1.0.dev5", commit_type) == "0.1.0"

    def test_no_prefix_falls_back_to_patch(self) -> None:
        commit_type = parse_commit_type("修复若干问题")
        assert release_version("0.1.0.dev5", commit_type) == "0.1.1"
