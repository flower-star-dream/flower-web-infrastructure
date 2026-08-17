"""PR 合入后自动发版脚本（GitHub Actions 调用）

@Author: 花海
@Date: 2026/08/17 22:00
@Description: dev→main 的 PR 合并成功后，自动在 main 生成正式版本：
              计算正式版本号并同步版本文件后，通过「release 分支 + PR 合并」通道合入 main——
              推送到 release/vX.Y.Z 临时分支 → 创建 PR（自动触发 CI）→ 等待检查通过 →
              自动合并 PR → 清理临时分支。全程走 PR 通道，使自动发版提交在推送 main 前
              已跑过 CI，规避 main 分支保护「推送前必须通过状态检查」的拦截。
              仅更新版本号，不打 tag（正式镜像发布仍由手动 v* tag 触发）。
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
        print("[release] --skip-git：未执行 git / GitHub API 操作")
        return 0

    token = os.environ.get("RELEASE_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print(
            "[release] 错误：缺少 RELEASE_TOKEN 环境变量（release.yml 需注入 secrets.RELEASE_PAT；"
            "本流程必须用 PAT，默认 GITHUB_TOKEN 创建的 PR 无法触发 CI）",
            file=sys.stderr,
        )
        return 1
    repo_env = os.environ.get("GITHUB_REPOSITORY")
    if repo_env:
        owner, repo = repo_env.split("/", 1)
    else:
        owner, repo = parse_repo_remote(git(["remote", "get-url", "origin"], repo_root))

    # 1) 创建版本提交
    git(["config", "user.name", "github-actions[bot]"], repo_root)
    git(["config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], repo_root)
    git(["add", *_VERSION_FILES], repo_root)
    git(["commit", "--no-verify", "-m", _RELEASE_COMMIT_SUBJECT.format(version=new_version)], repo_root)

    # 2) 推送 release 临时分支（不受 main 保护影响）
    release_branch = f"release/v{new_version}"
    git(["checkout", "-b", release_branch], repo_root)
    git(["push", "origin", release_branch], repo_root)
    print(f"[release] 已推送 release 分支 {release_branch}")

    # 3) 创建 PR：release/vX.Y.Z → main（自动触发 CI 检查）
    api = GitHubApi(token, owner, repo)
    pr_body = (
        "自动发版（由 release workflow 在 dev→main PR 合并后生成）：\n"
        f"- 正式版本：{current} → {new_version}\n"
        "- 同步更新 pyproject.toml / __init__.py / README / docs 版本引用\n"
        "- 仅更新版本号，不打 tag；CI 检查通过后自动合并"
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

    # 5) 清理临时分支（失败不阻断，交由人工处理）
    try:
        api.delete_branch(release_branch)
        print(f"[release] 已清理临时分支 {release_branch}")
    except Exception as exc:  # noqa: BLE001 - 清理失败不影响发版结果
        print(f"[release] 警告：清理临时分支失败（{exc}），请手动删除 {release_branch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
