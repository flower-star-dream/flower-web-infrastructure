"""自动版本管理脚本单元测试

@Author: 花海
@Date: 2026/08/17 21:10
@Description: 覆盖 scripts/version_bump.py 的提交类型解析、版本递增规则
              （正式分支 / dev 分支 / 跳过场景）与版本文件读写逻辑。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from version_bump import (  # noqa: E402
    CommitType,
    bump_version,
    parse_commit_type,
    read_current_version,
    write_version,
)


class TestParseCommitType:
    """提交信息 → 提交类型解析。"""

    def test_feat(self) -> None:
        assert parse_commit_type("feat: 新增订单能力") is CommitType.FEAT

    def test_feat_with_scope(self) -> None:
        assert parse_commit_type("feat(payment): 新增微信支付") is CommitType.FEAT

    def test_fix(self) -> None:
        assert parse_commit_type("fix: 修复并发问题") is CommitType.PATCH

    def test_refactor_perf_as_patch(self) -> None:
        for prefix in ("refactor", "perf"):
            assert parse_commit_type(f"{prefix}: 调整") is CommitType.PATCH, prefix

    def test_toolchain_prefixes_no_change(self) -> None:
        # 测试/构建/CI/格式改动不改变库行为，不迭代版本（与 docs/chore 一致）
        for prefix in ("test", "build", "ci", "style"):
            assert parse_commit_type(f"{prefix}: 调整") is CommitType.NO_CHANGE, prefix

    def test_docs_no_change(self) -> None:
        assert parse_commit_type("docs: 更新说明文档") is CommitType.NO_CHANGE

    def test_chore_no_change(self) -> None:
        assert parse_commit_type("chore: 调整依赖") is CommitType.NO_CHANGE

    def test_bang_breaking(self) -> None:
        assert parse_commit_type("feat!: 破坏性重构") is CommitType.BREAKING
        assert parse_commit_type("fix!: 接口不兼容") is CommitType.BREAKING

    def test_breaking_change_footer(self) -> None:
        subject = "feat: 重构鉴权"
        body = "\n\nBREAKING CHANGE: 权限点命名调整，不兼容"
        assert parse_commit_type(subject, body) is CommitType.BREAKING

    def test_merge_subject_skip(self) -> None:
        assert parse_commit_type("Merge branch 'dev' into main") is CommitType.SKIP

    def test_merge_source_skip(self) -> None:
        assert parse_commit_type("合并 dev", source="merge") is CommitType.SKIP

    def test_squash_source_skip(self) -> None:
        assert parse_commit_type("合入功能", source="squash") is CommitType.SKIP

    def test_revert_skip(self) -> None:
        assert parse_commit_type("Revert \"feat: 新增订单能力\"") is CommitType.SKIP

    def test_no_prefix_falls_back_to_patch(self) -> None:
        assert parse_commit_type("修复若干问题") is CommitType.PATCH

    def test_case_insensitive_prefix(self) -> None:
        assert parse_commit_type("FEAT: 新功能") is CommitType.FEAT


class TestIsDevBranch:
    """开发分支判定。"""

    def test_exact_dev(self) -> None:
        from version_bump import is_dev_branch

        assert is_dev_branch("dev") is True

    def test_dev_prefix_suffix(self) -> None:
        from version_bump import is_dev_branch

        assert is_dev_branch("dev/feature-a") is True
        assert is_dev_branch("dev-feature") is True
        assert is_dev_branch("feature-dev") is True

    def test_main_and_empty(self) -> None:
        from version_bump import is_dev_branch

        assert is_dev_branch("main") is False
        assert is_dev_branch("master") is False
        assert is_dev_branch("") is False


class TestBumpVersion:
    """版本递增规则。"""

    def test_main_feat_minor(self) -> None:
        assert bump_version("0.2.0", CommitType.FEAT, "main") == "0.3.0"

    def test_main_patch(self) -> None:
        assert bump_version("0.2.0", CommitType.PATCH, "main") == "0.2.1"

    def test_main_breaking_major(self) -> None:
        assert bump_version("0.2.0", CommitType.BREAKING, "main") == "1.0.0"

    def test_minor_carry(self) -> None:
        assert bump_version("0.9.9", CommitType.FEAT, "main") == "0.10.0"

    def test_major_reset_minor_patch(self) -> None:
        assert bump_version("2.9.9", CommitType.BREAKING, "main") == "3.0.0"

    def test_dev_first_commit(self) -> None:
        assert bump_version("0.2.0", CommitType.FEAT, "dev") == "0.2.0-dev0"
        assert bump_version("0.2.0", CommitType.PATCH, "dev") == "0.2.0-dev0"

    def test_dev_increment_dev_number(self) -> None:
        assert bump_version("0.2.0-dev3", CommitType.FEAT, "dev") == "0.2.0-dev4"
        assert bump_version("0.2.0-dev3", CommitType.PATCH, "dev") == "0.2.0-dev4"

    def test_dev_branch_pattern(self) -> None:
        assert bump_version("0.2.0-dev1", CommitType.PATCH, "feature-dev") == "0.2.0-dev2"

    def test_main_strip_dev_then_bump(self) -> None:
        assert bump_version("0.2.0-dev5", CommitType.FEAT, "main") == "0.3.0"
        assert bump_version("0.2.0-dev5", CommitType.PATCH, "main") == "0.2.1"
        assert bump_version("0.2.0-dev5", CommitType.BREAKING, "main") == "1.0.0"

    def test_no_change_returns_none(self) -> None:
        assert bump_version("0.2.0", CommitType.NO_CHANGE, "main") is None
        assert bump_version("0.2.0-dev0", CommitType.SKIP, "dev") is None

    def test_invalid_version_raises(self) -> None:
        with pytest.raises(ValueError):
            bump_version("abc", CommitType.FEAT, "main")

    def test_leading_zero_rejected(self) -> None:
        # SemVer 规范：MAJOR/MINOR/PATCH 为非负整数且禁止前导零
        for bad in ("01.2.3", "1.02.3", "1.2.03"):
            with pytest.raises(ValueError):
                bump_version(bad, CommitType.FEAT, "main")

    def test_unsupported_prerelease_rejected(self) -> None:
        # SemVer 预发布格式仅支持 -devN（框架暂只使用 dev 预发布）
        for bad in ("1.2.3-alpha.1", "1.2.3-01", "1.2.3+build.1"):
            with pytest.raises(ValueError):
                bump_version(bad, CommitType.FEAT, "main")


class TestVersionFileIO:
    """版本文件读写（代码 + 文档引用同步）。"""

    def test_read_and_write_version(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "flower-web-infrastructure"\nversion = "0.2.0"\n', encoding="utf-8"
        )
        init_dir = tmp_path / "src" / "web_infra"
        init_dir.mkdir(parents=True)
        init_file = init_dir / "__init__.py"
        init_file.write_text('__version__ = "0.2.0"\n', encoding="utf-8")

        assert read_current_version(tmp_path) == "0.2.0"
        write_version(tmp_path, "0.2.0", "0.3.0")
        assert pyproject.read_text(encoding="utf-8") == (
            '[project]\nname = "flower-web-infrastructure"\nversion = "0.3.0"\n'
        )
        assert init_file.read_text(encoding="utf-8") == '__version__ = "0.3.0"\n'

    def test_write_version_syncs_docs_only_current_version(self, tmp_path: Path) -> None:
        """文档同步：更新当前版本展示位与演示示例基数，不误伤数据库迁移版本。"""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "flower-web-infrastructure"\nversion = "0.1.0"\n', encoding="utf-8"
        )
        init_dir = tmp_path / "src" / "web_infra"
        init_dir.mkdir(parents=True)
        (init_dir / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")

        readme = tmp_path / "README.md"
        readme.write_text(
            "[![version](https://img.shields.io/badge/version-v0.1.0-blue)](url)\n"
            "| 当前版本 | v0.1.0 |\n"
            "| `feat` | `0.1.0` → `0.2.0` |\n"
            "| `fix` | `0.1.0` → `0.1.1` |\n"
            "| BREAKING | `0.1.0` → `1.0.0` |\n"
            "- 当前版本：**v0.1.0**（与 `pyproject.toml` 保持同步）。\n"
            "增量脚本：`V0.2.0-mq-outbox-next-retry-ddl.sql`\n",
            encoding="utf-8",
        )
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "CI-CD.md").write_text("如 tag `v0.1.0` → 推送 `v0.1.0`（与 pyproject.toml 保持一致）\n", encoding="utf-8")
        (docs_dir / "使用说明.md").write_text('pip install "git+https://github.com/<org>/flower-web-infrastructure.git@v0.1.0"\n', encoding="utf-8")

        write_version(tmp_path, "0.1.0", "0.2.0")

        expected_readme = (
            "[![version](https://img.shields.io/badge/version-v0.2.0-blue)](url)\n"
            "| 当前版本 | v0.2.0 |\n"
            # 演示示例以新基础版本为基数整体重算（feat→minor、fix→patch、breaking→major）
            "| `feat` | `0.2.0` → `0.3.0` |\n"
            "| `fix` | `0.2.0` → `0.2.1` |\n"
            "| BREAKING | `0.2.0` → `1.0.0` |\n"
            "- 当前版本：**v0.2.0**（与 `pyproject.toml` 保持同步）。\n"
            # 数据库迁移版本不误伤
            "增量脚本：`V0.2.0-mq-outbox-next-retry-ddl.sql`\n"
        )
        assert readme.read_text(encoding="utf-8") == expected_readme
        assert (docs_dir / "CI-CD.md").read_text(encoding="utf-8") == "如 tag `v0.2.0` → 推送 `v0.2.0`（与 pyproject.toml 保持一致）\n"
        assert (docs_dir / "使用说明.md").read_text(encoding="utf-8") == 'pip install "git+https://github.com/<org>/flower-web-infrastructure.git@v0.2.0"\n'


class TestSyncReadmeExamples:
    """README 演示示例（规则示例表 / 开发分支示例 / 合入指南）随基础版本同步。"""

    def _sync(self, text: str, old: str, new: str) -> str:
        from version_bump import _sync_readme_examples

        return _sync_readme_examples(text, old, new)

    def test_example_table_rows(self) -> None:
        text = (
            "| `feat` | 小版本 +1 | `0.1.0` → `0.2.0` |\n"
            "| `fix` | 补丁 +1 | `0.1.0` → `0.1.1` |\n"
            "| 含 `BREAKING CHANGE:` | 大版本 +1 | `0.1.0` → `1.0.0` |\n"
            "| 其他无前缀提交 | 按补丁 +1 | `0.1.0` → `0.1.1` |\n"
        )
        expected = (
            "| `feat` | 小版本 +1 | `0.2.0` → `0.3.0` |\n"
            "| `fix` | 补丁 +1 | `0.2.0` → `0.2.1` |\n"
            "| 含 `BREAKING CHANGE:` | 大版本 +1 | `0.2.0` → `1.0.0` |\n"
            "| 其他无前缀提交 | 按补丁 +1 | `0.2.0` → `0.2.1` |\n"
        )
        assert self._sync(text, "0.1.0", "0.2.0") == expected

    def test_dev_branch_example(self) -> None:
        text = (
            "- **开发分支**：打测试版本号（SemVer），如 `0.1.0` → `0.1.0-dev0` → `0.1.0-dev1`；"
            "（如 `0.1.0-dev5` + fix → `0.1.1`）。\n"
        )
        expected = (
            "- **开发分支**：打测试版本号（SemVer），如 `0.2.0` → `0.2.0-dev0` → `0.2.0-dev1`；"
            "（如 `0.2.0-dev5` + fix → `0.2.1`）。\n"
        )
        assert self._sync(text, "0.1.0", "0.2.0") == expected

    def test_merge_guide_examples(self) -> None:
        text = (
            "- 合入前 dev 版本为 `0.1.0-dev5`，合入后 main 上 `feat` 提交 → 剥离 `-devN` 得 `0.1.0` "
            "→ 小版本 +1 → **`0.2.0`**（正式版）。\n"
            "> 手动打 tag 推送即可（`git tag v0.2.0 && git push origin v0.2.0`）。\n"
        )
        expected = (
            "- 合入前 dev 版本为 `0.2.0-dev5`，合入后 main 上 `feat` 提交 → 剥离 `-devN` 得 `0.2.0` "
            "→ 小版本 +1 → **`0.3.0`**（正式版）。\n"
            "> 手动打 tag 推送即可（`git tag v0.3.0 && git push origin v0.3.0`）。\n"
        )
        assert self._sync(text, "0.1.0", "0.2.0") == expected

    def test_db_migration_reference_not_touched(self) -> None:
        text = (
            "迁移链：`0001_message_outbox`（基线）→ `0002_add_next_retry_at`（等价 `V0.2.0-mq-outbox-next-retry-ddl.sql` 语义）。\n"
            "| `fix` | `0.1.0` → `0.1.1` |\n"
        )
        expected = (
            "迁移链：`0001_message_outbox`（基线）→ `0002_add_next_retry_at`（等价 `V0.2.0-mq-outbox-next-retry-ddl.sql` 语义）。\n"
            "| `fix` | `0.2.0` → `0.2.1` |\n"
        )
        assert self._sync(text, "0.1.0", "0.2.0") == expected

    def test_dev_base_unchanged_no_sync(self) -> None:
        # dev 分支基础版本不变（0.1.0-dev0 → 0.1.0-dev1），示例不更新
        text = "| `feat` | `0.1.0` → `0.2.0` |\n"
        assert self._sync(text, "0.1.0-dev0", "0.1.0-dev1") == text
