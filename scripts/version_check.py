"""版本文件一致性校验与暂存（pre-commit 钩子）

@Author: 花海
@Date: 2026/08/18 00:00
@Description: release-only 版本机制（2026-08-18 整改）下的 pre-commit 钩子：
              1) 校验版本文件一致性——pyproject.toml（权威）、src/web_infra/__init__.py、
                 README 当前版本展示位（徽章 / 项目信息表 / §13）三处版本号必须一致，
                 不一致时阻止提交（防止发布版本号漂移，如手动改 pyproject 未同步文档）；
              2) 版本文件存在变更时自动 git add（pre-commit 中 index 修改随本次提交生效，
                 保证手动/发布流程更新的版本文件入库，不再残留暂存区）。
              版本递增不由本地提交触发：正式版由 dev→main 合入时 release workflow 自动生成
              （scripts/release_after_merge.py），本地仅做校验与暂存。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from version_bump import (  # noqa: E402
    _DOC_VERSION_RULES,
    _INIT_VERSION_RE,
    _VERSION_FILES,
    git,
    read_current_version,
)


def check_version_consistency(repo_root: Path) -> list[str]:
    """校验版本文件一致性，返回不一致描述列表（空列表 = 一致）。

    :param repo_root: 仓库根目录
    :return: 不一致描述列表
    :raises RuntimeError: 权威版本（pyproject.toml）解析失败
    """
    problems: list[str] = []
    current = read_current_version(repo_root)

    # 1) 代码版本：src/web_infra/__init__.py 的 __version__ 必须与 pyproject.toml 一致
    init_path = repo_root / "src" / "web_infra" / "__init__.py"
    if not init_path.exists():
        problems.append(f"缺失 {init_path.relative_to(repo_root)}")
    else:
        init_text = init_path.read_text(encoding="utf-8")
        m = _INIT_VERSION_RE.search(init_text)
        if m is None:
            problems.append("src/web_infra/__init__.py 未找到 __version__ 字段")
        else:
            init_version = m.group(0).split('"')[1]
            if init_version != current:
                problems.append(
                    f"src/web_infra/__init__.py 版本 {init_version} 与 pyproject.toml {current} 不一致"
                )

    # 2) 文档当前版本展示位（徽章 / 项目信息表 / §13 / docs 示例）必须包含当前版本
    for rel_path, template in _DOC_VERSION_RULES:
        doc_path = repo_root / rel_path
        if not doc_path.exists():
            continue
        text = doc_path.read_text(encoding="utf-8")
        if re.search(template.format(v=re.escape(current)), text) is None:
            problems.append(f"{rel_path} 缺少当前版本引用 v{current}（规则：{template}）")

    return problems


def stage_version_files(repo_root: Path) -> None:
    """暂存版本文件（git add，幂等；pre-commit 中 index 修改随本次提交生效）。

    :param repo_root: 仓库根目录
    """
    git(["add", *_VERSION_FILES], repo_root)


def main() -> int:
    """pre-commit 钩子入口：校验版本一致性 → 暂存版本文件。

    :return: 退出码（0 通过；1 版本不一致，阻止提交）
    """
    repo_root = Path(__file__).resolve().parents[1]

    try:
        problems = check_version_consistency(repo_root)
    except Exception as exc:  # noqa: BLE001 - 解析失败视为校验不通过，阻止提交暴露问题
        print(f"[version-check] 错误：版本校验失败（{exc}）", file=sys.stderr)
        return 1

    if problems:
        for problem in problems:
            print(f"[version-check] {problem}", file=sys.stderr)
        print(
            "[version-check] 版本不一致，已阻止提交。请先同步版本文件"
            "（pyproject.toml / src/web_infra/__init__.py / README / docs）后重试。",
            file=sys.stderr,
        )
        return 1

    stage_version_files(repo_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
