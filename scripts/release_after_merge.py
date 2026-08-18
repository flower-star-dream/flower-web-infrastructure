"""PR 合入后自动发版脚本（GitHub Actions 调用）

@Author: 花海
@Date: 2026/08/17 22:00
@Description: dev→main 的 PR 合并成功后，自动在 main 生成正式版本：
              计算正式版本号并同步版本文件后，通过「release 分支 + PR 合并」通道合入 main——
              推送到 release/vX.Y.Z 临时分支（推送前自动清理上次运行失败遗留的同名分支，
              避免 non-fast-forward 拒绝）→ 创建 PR（自动触发 CI）→ 等待检查通过 →
              自动合并 PR → 清理临时分支。全程走 PR 通道，使自动发版提交在推送 main 前
              已跑过 CI，规避 main 分支保护「推送前必须通过状态检查」的拦截。
              PR 合并后自动打 vX.Y.Z tag 并推送，触发 ci.yml 正式版镜像发布
              （SemVer + latest），发版一步到位，无需手动打 tag。
              由 .github/workflows/release.yml 在 pull_request closed+merged 时调用。

Token 说明：
    - 默认读取 RELEASE_TOKEN（推荐，release workflow 注入的 PAT），缺失时回退 GITHUB_TOKEN；
    - 本流程【必须】使用具备 repo scope（contents + pull_requests 写权限）的 PAT，
      不能只用默认 GITHUB_TOKEN——GitHub 规定用 GITHUB_TOKEN 创建 PR / 推送不会触发新的
      workflow run，发版 PR 将无法触发 CI（wait_for_checks 必然超时），且 pull_request 事件
      下用 GITHUB_TOKEN 创建 PR 常被 403 拒绝（Resource not accessible by integration）。

用法：
    python scripts/release_after_merge.py --pr-title "<PR 标题>"    # 需 RELEASE_TOKEN 或 GITHUB_TOKEN 环境变量
    python scripts/release_after_merge.py --pr-title "feat: xxx" --skip-git   # 仅计算与更新文件
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

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

# 自动发版提交信息（release 分支上的版本提交）
_RELEASE_COMMIT_SUBJECT = "chore(release): 发布正式版 v{version}"

# 等待 CI 检查的默认超时/间隔（秒），可用环境变量覆盖
_DEFAULT_CHECK_TIMEOUT = 900
_DEFAULT_CHECK_INTERVAL = 20

_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _raise_for_status(response: httpx.Response) -> None:
    """非 2xx 响应抛出带响应体正文的异常（GitHub API 报错多为 403/422，正文含具体原因）。

    :param response: httpx 响应
    :raises httpx.HTTPStatusError: 异常信息含状态码与响应体前 500 字符
    """
    if response.is_success:
        return
    detail = response.text[:500].strip() or response.reason_phrase
    message = f"GitHub API {response.request.method} {response.url.path} -> {response.status_code}: {detail}"
    raise httpx.HTTPStatusError(message, request=response.request, response=response)


def release_version(current: str, commit_type: CommitType) -> str | None:
    """计算合入 main 后的正式版本号。

    main 分支发版语义：
    - 带 -devN 预发布后缀：先剥离；docs/chore 仅剥离正式化（不递增），其余按类型递增；
    - 不带 -devN：docs/chore 不变（返回 None），其余按类型递增。

    :param current: main 分支当前版本（X.Y.Z 或 X.Y.Z-devN，SemVer 规范）
    :param commit_type: PR 标题解析出的提交类型
    :return: 正式版本号；None 表示无需更新
    :raises ValueError: 当前版本号格式非法
    """
    if commit_type is CommitType.SKIP:
        return None

    m = _VERSION_RE.match(current)
    if m is None:
        raise ValueError(f"无法解析版本号: {current!r}（期望 X.Y.Z 或 X.Y.Z-devN，SemVer 规范）")
    major, minor, patch = int(m.group("major")), int(m.group("minor")), int(m.group("patch"))
    has_dev = m.group("dev") is not None

    # docs/chore：仅剥离 -devN 正式化，不递增；无 -devN 时不更新
    if commit_type is CommitType.NO_CHANGE:
        return None if not has_dev else f"{major}.{minor}.{patch}"

    # 正式发版：剥离 -devN（若有）后按提交类型递增基础版本
    if commit_type is CommitType.BREAKING:
        return f"{major + 1}.0.0"
    if commit_type is CommitType.FEAT:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def detect_breaking_in_pr(messages: list[str]) -> bool:
    """从 PR 提交历史检测破坏性变更标记（feat! / BREAKING CHANGE: footer）。

    发版版本语义兜底：release workflow 依据 dev→main PR 标题解析提交类型，
    标题漏标 `!` / BREAKING CHANGE 时会误发小版本（如三层重构应发 1.0.0 却发 0.2.0）。
    本函数遍历 PR 参与合并的提交信息，复用 version_bump.parse_commit_type 的
    breaking 判定（前缀带 `!` 或正文含 `BREAKING CHANGE:` / `BREAKING-CHANGE:`），
    命中任一提交即视为破坏性变更，用于把版本语义升级为大版本。

    :param messages: PR 提交 message 列表
    :return: True 表示提交历史中存在破坏性变更标记
    """
    for message in messages:
        lines = message.splitlines()
        subject = lines[0] if lines else ""
        body = "\n".join(lines[1:])
        if parse_commit_type(subject, body) is CommitType.BREAKING:
            return True
    return False


def should_detect_breaking(commit_type: CommitType) -> bool:
    """判断是否需要对 dev→main PR 提交历史做 breaking 兜底检测。

    兜底语义是「PR 标题漏标 `!` / BREAKING CHANGE」：仅对会递增版本的提交类型
    （feat / fix 等）生效。docs / chore（NO_CHANGE）与 merge / revert（SKIP）不参与
    版本递增，跳过检测，避免 docs PR 合入时被 dev 分支历史中的 breaking 提交误升级
    发大版本（如 PR 标题 docs: 却发布 v2.0.0）。

    :param commit_type: 由 PR 标题解析出的提交类型
    :return: True 表示需要对提交历史做 breaking 兜底检测
    """
    return commit_type in (CommitType.FEAT, CommitType.PATCH)


def parse_repo_remote(remote_url: str) -> tuple[str, str]:
    """从 git remote URL 解析 (owner, repo)。

    支持 https://github.com/owner/repo(.git) 与 git@github.com:owner/repo(.git) 两种格式。

    :param remote_url: git remote 地址
    :return: (owner, repo)
    :raises ValueError: 无法解析的地址
    """
    url = remote_url.strip()
    if url.endswith(".git"):
        url = url[:-4]
    if "github.com/" in url:
        path = url.split("github.com/", 1)[1]
    elif "github.com:" in url:
        path = url.split("github.com:", 1)[1]
    else:
        raise ValueError(f"无法解析 GitHub 仓库地址: {remote_url!r}")
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"无法解析 GitHub 仓库地址: {remote_url!r}")
    return parts[0], parts[1]


def evaluate_check_runs(runs: list[dict]) -> tuple[str, list[str]]:
    """评估 check runs 集合的完成状态。

    :param runs: GitHub check-runs 接口返回的 check_runs 列表
    :return: (status, 明细)，status ∈ success / failure / pending；明细为失败或未完成项名称
    """
    if not runs:
        return "pending", []
    if any(r.get("status") != "completed" for r in runs):
        return "pending", [r.get("name", "?") for r in runs if r.get("status") != "completed"]
    failed = [r.get("name", "?") for r in runs if r.get("conclusion") != "success"]
    if failed:
        return "failure", failed
    return "success", []


class GitHubApi:
    """GitHub REST API 客户端（httpx，支持注入 transport 便于测试）。"""

    def __init__(self, token: str, owner: str, repo: str, transport: httpx.BaseTransport | None = None) -> None:
        """初始化客户端。

        :param token: GitHub Token（GITHUB_TOKEN）
        :param owner: 仓库属主
        :param repo: 仓库名
        :param transport: 可选的 httpx transport（测试注入 MockTransport）
        """
        headers = {**_API_HEADERS, "Authorization": f"Bearer {token}"}
        self._client = httpx.Client(
            base_url=f"https://api.github.com/repos/{owner}/{repo}",
            headers=headers,
            transport=transport,
        )

    def create_pull(self, title: str, head: str, base: str, body: str) -> int:
        """创建 PR，返回 PR 编号。

        :param title: PR 标题
        :param head: 源分支
        :param base: 目标分支
        :param body: PR 描述
        :return: PR 编号
        :raises httpx.HTTPStatusError: API 报错（403 时附带 GITHUB_TOKEN 无法创建发版 PR 的提示）
        """
        response = self._client.post("/pulls", json={"title": title, "head": head, "base": base, "body": body})
        if response.status_code == 403:
            raise httpx.HTTPStatusError(
                "创建发版 PR 被拒绝（403）：请确认 RELEASE_TOKEN 为具备 contents + pull_requests 写权限的 PAT。"
                "GitHub 规定 pull_request 事件下用默认 GITHUB_TOKEN 创建 PR 常被 403（Resource not accessible"
                " by integration），且其创建的 PR 无法触发 CI。",
                request=response.request,
                response=response,
            )
        _raise_for_status(response)
        return int(response.json()["number"])

    def list_check_runs(self, sha: str) -> list[dict]:
        """查询提交上的全部 check runs。

        :param sha: 提交 SHA
        :return: check_runs 列表
        :raises httpx.HTTPStatusError: API 报错（含响应体）
        """
        response = self._client.get(f"/commits/{sha}/check-runs")
        _raise_for_status(response)
        return list(response.json().get("check_runs", []))

    def find_pull(self, base: str, head: str) -> int | None:
        """按 base/head 查找已合并 PR 的编号（用于发版前读取 dev→main 提交历史）。

        :param base: 目标分支（如 main）
        :param head: 源分支（同仓库直接用分支名，如 dev）
        :return: PR 编号；未找到返回 None
        :raises httpx.HTTPStatusError: API 报错（含响应体）
        """
        response = self._client.get("/pulls", params={"base": base, "head": head, "state": "all"})
        _raise_for_status(response)
        pulls = response.json()
        return int(pulls[0]["number"]) if pulls else None

    def list_pull_commits(self, pr_number: int) -> list[str]:
        """列出 PR 的提交信息（合并后仍可用，返回参与合并的提交）。

        :param pr_number: PR 编号
        :return: 提交 message 列表
        :raises httpx.HTTPStatusError: API 报错（含响应体）
        """
        response = self._client.get(f"/pulls/{pr_number}/commits", params={"per_page": 100})
        _raise_for_status(response)
        return [commit.get("commit", {}).get("message", "") for commit in response.json()]

    def merge_pull(self, number: int, method: str = "squash") -> None:
        """合并 PR。

        :param number: PR 编号
        :param method: 合并方式（merge / squash / rebase）
        :raises RuntimeError: PR 不可合并（405）时
        :raises httpx.HTTPStatusError: 其他 API 报错（含响应体）
        """
        response = self._client.put(f"/pulls/{number}/merge", json={"merge_method": method})
        if response.status_code == 405:
            raise RuntimeError(f"PR #{number} 不可合并: {response.text}")
        _raise_for_status(response)

    def delete_branch(self, branch: str) -> None:
        """删除分支（合并后清理临时分支；分支不存在时忽略）。

        :param branch: 分支名
        :raises httpx.HTTPStatusError: 其他 API 报错（含响应体）
        """
        response = self._client.delete(f"/git/refs/heads/{branch}")
        if response.status_code not in (204, 422):
            _raise_for_status(response)


def wait_for_checks(api: GitHubApi, sha: str, timeout_seconds: int, interval_seconds: int) -> None:
    """轮询等待提交的 CI 检查全部通过。

    :param api: GitHubApi 实例
    :param sha: 提交 SHA
    :param timeout_seconds: 超时时间
    :param interval_seconds: 轮询间隔
    :raises RuntimeError: 存在失败的检查
    :raises TimeoutError: 等待超时
    """
    deadline = time.monotonic() + timeout_seconds
    while True:
        status, details = evaluate_check_runs(api.list_check_runs(sha))
        if status == "success":
            return
        if status == "failure":
            raise RuntimeError(f"CI 检查失败: {', '.join(details)}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"等待 CI 检查超时（{timeout_seconds}s）：{', '.join(details) or '无检查记录'}")
        print(f"[release] 等待 CI 检查完成...（{', '.join(details) or '无检查记录'}）")
        time.sleep(interval_seconds)


def _clean_stale_release_branch(repo_root: Path, release_branch: str) -> None:
    """清理上次运行失败遗留的同名远端 release 分支。

    main 未达到目标版本时，同名远端分支必为上次运行残留（如推送成功但创建 PR 失败），
    直接推送会因 non-fast-forward 被拒；先删除再推送保证流程可重复执行。

    :param repo_root: 仓库根目录
    :param release_branch: release 分支名（如 release/v0.1.1）
    """
    if git(["ls-remote", "--heads", "origin", release_branch], repo_root).strip():
        print(f"[release] 远端已存在 {release_branch}（疑似上次运行残留），清理后重新推送")
        git(["push", "origin", "--delete", release_branch], repo_root)


def ensure_and_push_tag(repo_root: Path, new_version: str) -> None:
    """确保远端存在正式版本 tag 并推送（触发 ci.yml 正式版镜像发布）。

    幂等：远端已存在同名 tag 时跳过（如上次已推送成功但后续步骤失败，重跑时避免
    重复推送 / 本地同名 tag 冲突）。推送走 checkout 时注入的 PAT（origin remote 已
    带 token），tag 推送触发 ci.yml 的 v* 正式版镜像发布（SemVer + latest）。

    :param repo_root: 仓库根目录
    :param new_version: 正式版本号（X.Y.Z）
    """
    tag = f"v{new_version}"
    if git(["ls-remote", "--tags", "origin", tag], repo_root).strip():
        print(f"[release] 远端已存在 {tag}，跳过推送")
        return
    git(["tag", tag], repo_root)
    git(["push", "origin", tag], repo_root)
    print(f"[release] 已推送版本 tag {tag}，触发 CI 正式版镜像发布（SemVer + latest）")


def main() -> int:
    """入口：解析 PR 标题 → 计算正式版本 → 更新版本文件 → release 分支 PR 合入 main。

    :return: 退出码（发版失败时非 0，暴露给 CI 排查）
    """
    parser = argparse.ArgumentParser(description="PR 合入后自动发版（经 release 分支 PR 合入 main）")
    parser.add_argument("--pr-title", required=True, help="PR 标题（解析 conventional commits 前缀）")
    parser.add_argument(
        "--skip-git", action="store_true",
        help="仅计算与更新版本文件，不执行 git / GitHub API 操作（本地调试用）",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    commit_type = parse_commit_type(args.pr_title)
    if commit_type is CommitType.SKIP:
        print(f"[release] 跳过：PR 标题为 merge/revert 场景（{args.pr_title!r}）")
        return 0

    # 非 --skip-git 模式需要 GitHub API（Token 要求见模块文档）
    token = os.environ.get("RELEASE_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not args.skip_git and not token:
        print(
            "[release] 错误：缺少 RELEASE_TOKEN 环境变量（release.yml 需注入 secrets.RELEASE_PAT；"
            "本流程必须用 PAT，默认 GITHUB_TOKEN 创建的 PR 无法触发 CI）",
            file=sys.stderr,
        )
        return 1

    api: GitHubApi | None = None
    if not args.skip_git:
        repo_env = os.environ.get("GITHUB_REPOSITORY")
        if repo_env:
            owner, repo = repo_env.split("/", 1)
        else:
            owner, repo = parse_repo_remote(git(["remote", "get-url", "origin"], repo_root))
        api = GitHubApi(token, owner, repo)

        # 版本语义兜底（BREAKING）：PR 标题漏标 `!` / BREAKING CHANGE 时，
        # 从 dev→main 提交历史检测破坏性标记并升级为大版本（如三层重构应发 1.0.0 而非 0.2.0）。
        # 仅对会递增版本的提交类型（feat / fix 等）检测；docs / chore（NO_CHANGE）与
        # merge / revert（SKIP）跳过，避免 docs PR 合入被历史 breaking 提交误升级发版
        if should_detect_breaking(commit_type):
            try:
                pr_number = api.find_pull(base="main", head="dev")
                if pr_number is not None and detect_breaking_in_pr(api.list_pull_commits(pr_number)):
                    print("[release] dev→main PR 提交历史检测到 BREAKING CHANGE（! 或 BREAKING CHANGE:），升级为大版本")
                    commit_type = CommitType.BREAKING
            except Exception as exc:  # noqa: BLE001 - 检测失败不阻断发版，回退 PR 标题语义
                print(f"[release] 警告：PR 提交历史 breaking 检测失败（{exc}），按 PR 标题解析结果发版")

    current = read_current_version(repo_root)
    new_version = release_version(current, commit_type)
    if new_version is None:
        print(f"[release] 无版本变更（docs/chore 且 main 无 -devN 预发布后缀），当前版本 {current}")
        return 0
    if new_version == current:
        print(f"[release] 版本无变化（{current}），跳过")
        return 0

    write_version(repo_root, current, new_version)
    print(f"[release] 正式版本已生成: {current} -> {new_version}")

    if args.skip_git:
        print("[release] --skip-git：未执行 git / GitHub API 操作")
        return 0

    # 1) 创建版本提交
    git(["config", "user.name", "github-actions[bot]"], repo_root)
    git(["config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], repo_root)
    git(["add", *_VERSION_FILES], repo_root)
    git(["commit", "--no-verify", "-m", _RELEASE_COMMIT_SUBJECT.format(version=new_version)], repo_root)

    # 2) 推送 release 临时分支（不受 main 保护影响）
    release_branch = f"release/v{new_version}"
    # 清理上次运行失败遗留的同名远端分支，避免 non-fast-forward 拒绝
    _clean_stale_release_branch(repo_root, release_branch)
    git(["checkout", "-b", release_branch], repo_root)
    git(["push", "origin", release_branch], repo_root)
    print(f"[release] 已推送 release 分支 {release_branch}")

    # 3) 创建 PR：release/vX.Y.Z → main（自动触发 CI 检查）
    assert api is not None  # 非 --skip-git 模式已在上方实例化
    pr_body = (
        "自动发版（由 release workflow 在 dev→main PR 合并后生成）：\n"
        f"- 正式版本：{current} → {new_version}\n"
        "- 同步更新 pyproject.toml / __init__.py / README / docs 版本引用\n"
        f"- 合并后自动打 v{new_version} tag，触发 CI 正式版镜像发布（SemVer + latest）"
    )
    pr_number = api.create_pull(
        title=_RELEASE_COMMIT_SUBJECT.format(version=new_version),
        head=release_branch,
        base="main",
        body=pr_body,
    )
    print(f"[release] 已创建 PR #{pr_number}（{release_branch} → main）")

    # 4) 等待 CI 检查通过后自动合并（自动发版提交已跑过 CI，规避 main 推送保护）
    timeout = int(os.environ.get("RELEASE_CHECK_TIMEOUT", str(_DEFAULT_CHECK_TIMEOUT)))
    interval = int(os.environ.get("RELEASE_CHECK_INTERVAL", str(_DEFAULT_CHECK_INTERVAL)))
    head_sha = git(["rev-parse", "HEAD"], repo_root)
    wait_for_checks(api, head_sha, timeout, interval)
    print("[release] CI 检查全部通过，合并 PR...")
    api.merge_pull(pr_number, method="squash")
    print(f"[release] PR #{pr_number} 已合并，正式版本 {new_version} 已合入 main")

    # 5) 同步本地 main 到远端合并结果：PR 为 squash 合并，远端 main 的提交 SHA
    #    与本地不同（本地仍是含版本提交的临时提交），先 fetch + reset 使 HEAD
    #    指向远端正式提交，确保 tag 打在 main 历史链上（否则 tag 指向孤立提交，
    #    ci.yml 会基于错误的提交构建正式镜像）
    git(["fetch", "origin", "main"], repo_root)
    git(["checkout", "main"], repo_root)
    git(["reset", "--hard", "origin/main"], repo_root)

    # 6) 打正式版本 tag 并推送，触发 ci.yml 正式版镜像发布（SemVer + latest）
    ensure_and_push_tag(repo_root, new_version)

    # 7) 清理临时分支（失败不阻断，交由人工处理）
    try:
        api.delete_branch(release_branch)
        print(f"[release] 已清理临时分支 {release_branch}")
    except Exception as exc:  # noqa: BLE001 - 清理失败不影响发版结果
        print(f"[release] 警告：清理临时分支失败（{exc}），请手动删除 {release_branch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
