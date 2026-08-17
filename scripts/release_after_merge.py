"""PR 合入后自动发版脚本（GitHub Actions 调用）

@Author: 花海
@Date: 2026/08/17 22:00
@Description: dev→main 的 PR 合并成功后，在 main 分支自动生成正式版本：
              剥离 dev 测试版本号 .devN 并按 PR 标题前缀递增（feat→小版本、fix 等→补丁、
              ! 或 BREAKING CHANGE→大版本、docs/chore→仅剥离 .devN 正式化不递增），
              同步更新 pyproject.toml / __init__.py / README / docs 版本引用，
              提交并推送 main 分支。仅更新版本号，不打 tag（正式镜像发布仍由手动 v* tag 触发）。
              由 .github/workflows/release.yml 在 pull_request closed+merged 时调用。

用法：
    python scripts/release_after_merge.py --pr-title "<PR 标题>"
    python scripts/release_after_merge.py --pr-title "feat: xxx" --skip-git   # 仅计算与更新文件，不提交推送
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from version_bump import (  # noqa: E402
    CommitType,
    _VERSION_FILES,
    _VERSION_RE,
    git,
    parse_commit_type,
    read_current_version,
    write_version,
)

# 自动发版提交信息前缀（远端 main 上由 CI 生成的提交，本地钩子不会重复处理该提交）
_RELEASE_COMMIT_SUBJECT = "chore(release): 发布正式版 v{version}"


def release_version(current: str, commit_type: CommitType) -> str | None:
    """计算合入 main 后的正式版本号。

    main 分支发版语义：
    - 带 .devN 测试后缀：先剥离；docs/chore 仅剥离正式化（不递增），其余按类型递增；
    - 不带 .devN：docs/chore 不变（返回 None），其余按类型递增。

    :param current: main 分支当前版本（X.Y.Z 或 X.Y.Z.devN）
    :param commit_type: PR 标题解析出的提交类型
    :return: 正式版本号；None 表示无需更新
    :raises ValueError: 当前版本号格式非法
    """
    if commit_type is CommitType.SKIP:
        return None

    m = _VERSION_RE.match(current)
    if m is None:
        raise ValueError(f"无法解析版本号: {current!r}（期望 X.Y.Z 或 X.Y.Z.devN）")
    major, minor, patch = int(m.group("major")), int(m.group("minor")), int(m.group("patch"))
    has_dev = m.group("dev") is not None

    # docs/chore：仅剥离 .devN 正式化，不递增；无 .devN 时不更新
    if commit_type is CommitType.NO_CHANGE:
        return None if not has_dev else f"{major}.{minor}.{patch}"

    # 正式发版：剥离 .devN（若有）后按提交类型递增基础版本
    if commit_type is CommitType.BREAKING:
        return f"{major + 1}.0.0"
    if commit_type is CommitType.FEAT:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main() -> int:
    """入口：解析 PR 标题 → 计算正式版本 → 更新版本文件 → 提交并推送 main。

    :return: 退出码（发版失败时非 0，暴露给 CI 排查）
    """
    parser = argparse.ArgumentParser(description="PR 合入后自动发版（生成正式版本并推送 main）")
    parser.add_argument("--pr-title", required=True, help="PR 标题（解析 conventional commits 前缀）")
    parser.add_argument(
        "--skip-git", action="store_true",
        help="仅计算与更新版本文件，不执行 git add/commit/push（本地调试用）",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    commit_type = parse_commit_type(args.pr_title)
    if commit_type is CommitType.SKIP:
        print(f"[release] 跳过：PR 标题为 merge/revert 场景（{args.pr_title!r}）")
        return 0

    current = read_current_version(repo_root)
    new_version = release_version(current, commit_type)
    if new_version is None:
        print(f"[release] 无版本变更（docs/chore 且 main 无 .devN 测试后缀），当前版本 {current}")
        return 0
    if new_version == current:
        print(f"[release] 版本无变化（{current}），跳过")
        return 0

    write_version(repo_root, current, new_version)
    print(f"[release] 正式版本已生成: {current} -> {new_version}")

    if args.skip_git:
        print("[release] --skip-git：未执行 git 提交推送")
        return 0

    # CI 环境配置提交身份（actions/checkout 已注入 GITHUB_TOKEN 凭据，push 无需额外认证）
    git(["config", "user.name", "github-actions[bot]"], repo_root)
    git(["config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], repo_root)
    git(["add", *_VERSION_FILES], repo_root)
    git(["commit", "--no-verify", "-m", _RELEASE_COMMIT_SUBJECT.format(version=new_version)], repo_root)
    git(["push", "origin", "HEAD"], repo_root)
    print(f"[release] 已提交并推送 main（{_RELEASE_COMMIT_SUBJECT.format(version=new_version)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
