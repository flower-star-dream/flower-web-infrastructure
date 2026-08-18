"""pre-commit 版本校验脚本单元测试

@Author: 花海
@Date: 2026/08/18 00:00
@Description: 覆盖 scripts/version_check.py（release-only 版本机制的 pre-commit 钩子）：
              版本文件一致性校验（pyproject / __init__ / README / docs 版本引用必须一致）
              与版本文件暂存（git add _VERSION_FILES）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from version_check import check_version_consistency, stage_version_files  # noqa: E402


class _Repo:
    """构造版本文件齐全的临时仓库目录。"""

    def __init__(self, tmp_path: Path, version: str = "1.0.0") -> None:
        self.root = tmp_path
        (tmp_path / "pyproject.toml").write_text(
            f'[project]\nname = "flower-web-infrastructure"\nversion = "{version}"\n',
            encoding="utf-8",
        )
        init_dir = tmp_path / "src" / "web_infra"
        init_dir.mkdir(parents=True)
        (init_dir / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
        readme = (
            f"[![version](https://img.shields.io/badge/version-v{version}-blue)](url)\n"
            f"| 当前版本 | v{version} |\n"
            f"- 当前版本：**v{version}**（与 `pyproject.toml` 保持同步）。\n"
        )
        (tmp_path / "README.md").write_text(readme, encoding="utf-8")
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "CI-CD.md").write_text(f"如 tag `v{version}` → 推送 `v{version}`（与 pyproject.toml 保持一致）\n", encoding="utf-8")
        (docs_dir / "使用说明.md").write_text(
            f'pip install "git+https://github.com/<org>/flower-web-infrastructure.git@v{version}"\n',
            encoding="utf-8",
        )


class TestCheckVersionConsistency:
    """版本文件一致性校验。"""

    def test_all_consistent(self, tmp_path: Path) -> None:
        repo = _Repo(tmp_path, "1.0.0")
        assert check_version_consistency(repo.root) == []

    def test_dev_version_consistent(self, tmp_path: Path) -> None:
        repo = _Repo(tmp_path, "1.0.0-dev8")
        assert check_version_consistency(repo.root) == []

    def test_init_version_mismatch(self, tmp_path: Path) -> None:
        repo = _Repo(tmp_path, "1.0.0")
        init_path = repo.root / "src" / "web_infra" / "__init__.py"
        init_path.write_text('__version__ = "1.0.1"\n', encoding="utf-8")
        problems = check_version_consistency(repo.root)
        assert len(problems) == 1
        assert "__init__.py" in problems[0]
        assert "1.0.1" in problems[0]
        assert "1.0.0" in problems[0]

    def test_readme_missing_version_reference(self, tmp_path: Path) -> None:
        repo = _Repo(tmp_path, "1.0.0")
        # README 徽章版本位漂移（演示示例中的历史版本不影响校验，只查当前版本展示位）
        readme_path = repo.root / "README.md"
        readme_path.write_text(
            "[![version](https://img.shields.io/badge/version-v0.9.0-blue)](url)\n"
            "| 当前版本 | v1.0.0 |\n"
            "- 当前版本：**v1.0.0**（与 `pyproject.toml` 保持同步）。\n",
            encoding="utf-8",
        )
        problems = check_version_consistency(repo.root)
        assert any("README.md" in p for p in problems)

    def test_docs_missing_reference(self, tmp_path: Path) -> None:
        repo = _Repo(tmp_path, "1.0.0")
        (repo.root / "docs" / "CI-CD.md").write_text("如 tag `v0.9.0` → 推送 `v0.9.0`\n", encoding="utf-8")
        problems = check_version_consistency(repo.root)
        assert any("CI-CD.md" in p for p in problems)

    def test_missing_init_file(self, tmp_path: Path) -> None:
        repo = _Repo(tmp_path, "1.0.0")
        (repo.root / "src" / "web_infra" / "__init__.py").unlink()
        problems = check_version_consistency(repo.root)
        assert any("__init__.py" in p for p in problems)


class TestStageVersionFiles:
    """版本文件暂存（pre-commit 中 git add 生效）。"""

    def test_stage_calls_git_add_version_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        def fake_git(args: list[str], repo_root: Path) -> str:
            calls.append(args)
            return ""

        monkeypatch.setattr("version_check.git", fake_git)
        stage_version_files(tmp_path)
        assert calls == [["add", "pyproject.toml", "src/web_infra/__init__.py", "README.md", "docs/CI-CD.md", "docs/使用说明.md"]]
