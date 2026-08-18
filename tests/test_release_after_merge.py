"""自动发版脚本单元测试

@Author: 花海
@Date: 2026/08/17 22:00
@Description: 覆盖 scripts/release_after_merge.py 的正式版本计算规则（dev→main 合入发版）、
              git remote 解析、check runs 评估、GitHub API 客户端（httpx MockTransport）
              与等待检查轮询逻辑；API 错误路径验证响应体打印与 403（GITHUB_TOKEN 场景）提示。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
import pytest
from httpx import MockTransport, Request, Response

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from release_after_merge import (  # noqa: E402
    GitHubApi,
    _clean_stale_release_branch,
    detect_breaking_in_pr,
    ensure_and_push_tag,
    evaluate_check_runs,
    parse_repo_remote,
    release_version,
    wait_for_checks,
)
from version_bump import CommitType, parse_commit_type  # noqa: E402


class TestReleaseVersion:
    """正式版本计算规则（main 合入发版）。"""

    def test_dev_feat_bumps_minor(self) -> None:
        assert release_version("0.1.0-dev5", CommitType.FEAT) == "0.2.0"

    def test_dev_patch_bumps_patch(self) -> None:
        assert release_version("0.1.0-dev5", CommitType.PATCH) == "0.1.1"

    def test_dev_breaking_bumps_major(self) -> None:
        assert release_version("0.1.0-dev5", CommitType.BREAKING) == "1.0.0"

    def test_dev_docs_strip_only(self) -> None:
        # docs/chore 合入：仅剥离 -devN 正式化，不递增
        assert release_version("0.1.0-dev5", CommitType.NO_CHANGE) == "0.1.0"

    def test_no_dev_feat_bumps_minor(self) -> None:
        assert release_version("0.1.0", CommitType.FEAT) == "0.2.0"

    def test_no_dev_patch_bumps_patch(self) -> None:
        assert release_version("0.1.0", CommitType.PATCH) == "0.1.1"

    def test_no_dev_breaking_bumps_major(self) -> None:
        assert release_version("2.9.9", CommitType.BREAKING) == "3.0.0"

    def test_no_dev_docs_returns_none(self) -> None:
        # 无 -devN 时 docs/chore 不更新版本
        assert release_version("0.1.0", CommitType.NO_CHANGE) is None

    def test_skip_returns_none(self) -> None:
        assert release_version("0.1.0-dev3", CommitType.SKIP) is None

    def test_minor_carry(self) -> None:
        assert release_version("0.9.9", CommitType.FEAT) == "0.10.0"

    def test_invalid_version_raises(self) -> None:
        with pytest.raises(ValueError):
            release_version("abc", CommitType.FEAT)

    def test_leading_zero_rejected(self) -> None:
        # SemVer 规范：MAJOR/MINOR/PATCH 为非负整数且禁止前导零
        for bad in ("01.2.3", "1.02.3", "1.2.03"):
            with pytest.raises(ValueError):
                release_version(bad, CommitType.FEAT)


class TestReleaseFromPrTitle:
    """PR 标题 → 正式版本集成。"""

    def test_feat_pr_title(self) -> None:
        commit_type = parse_commit_type("feat: 新增订单能力")
        assert release_version("0.1.0-dev5", commit_type) == "0.2.0"

    def test_fix_pr_title(self) -> None:
        commit_type = parse_commit_type("fix: 修复并发问题")
        assert release_version("0.1.0-dev5", commit_type) == "0.1.1"

    def test_breaking_pr_title(self) -> None:
        commit_type = parse_commit_type("feat!: 破坏性重构")
        assert release_version("0.1.0-dev5", commit_type) == "1.0.0"

    def test_docs_pr_title(self) -> None:
        commit_type = parse_commit_type("docs: 更新说明文档")
        assert release_version("0.1.0-dev5", commit_type) == "0.1.0"

    def test_no_prefix_falls_back_to_patch(self) -> None:
        commit_type = parse_commit_type("修复若干问题")
        assert release_version("0.1.0-dev5", commit_type) == "0.1.1"


class TestDetectBreakingInPr:
    """PR 提交历史 breaking 检测（标题漏标 ! 时的版本语义兜底）。"""

    def test_feat_bang_detected(self) -> None:
        messages = ["feat: 新增缓存", "feat!: 重构三层结构\n\nBREAKING CHANGE: 子包路径迁移", "fix: 修复 bug"]
        assert detect_breaking_in_pr(messages) is True

    def test_breaking_change_footer_detected(self) -> None:
        # 前缀不带 !，但正文含 BREAKING CHANGE: footer
        messages = ["feat: 重构\n\nBREAKING CHANGE: 接口不兼容"]
        assert detect_breaking_in_pr(messages) is True

    def test_no_breaking_not_detected(self) -> None:
        messages = ["feat: 新增缓存", "fix: 修复 bug", "docs: 更新文档"]
        assert detect_breaking_in_pr(messages) is False

    def test_empty_messages(self) -> None:
        assert detect_breaking_in_pr([]) is False

    def test_squash_single_message(self) -> None:
        # squash 合并后单条提交信息
        assert detect_breaking_in_pr(["feat: 合并多个功能"]) is False
        assert detect_breaking_in_pr(["feat!: 合并破坏性重构"]) is True


class TestParseRepoRemote:
    """git remote URL 解析。"""

    def test_https_url(self) -> None:
        assert parse_repo_remote("https://github.com/flower-star-dream/flower-web-infrastructure.git") == (
            "flower-star-dream", "flower-web-infrastructure",
        )

    def test_https_url_without_git_suffix(self) -> None:
        assert parse_repo_remote("https://github.com/o/r") == ("o", "r")

    def test_ssh_url(self) -> None:
        assert parse_repo_remote("git@github.com:flower-star-dream/flower-web-infrastructure.git") == (
            "flower-star-dream", "flower-web-infrastructure",
        )

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_repo_remote("https://gitlab.com/o/r.git")


class TestEvaluateCheckRuns:
    """check runs 状态评估。"""

    @staticmethod
    def _run(name: str, status: str = "completed", conclusion: str = "success") -> dict:
        return {"name": name, "status": status, "conclusion": conclusion}

    def test_empty_pending(self) -> None:
        assert evaluate_check_runs([]) == ("pending", [])

    def test_all_success(self) -> None:
        runs = [self._run("静态检查 + 单元测试"), self._run("构建 Docker 基础镜像")]
        assert evaluate_check_runs(runs) == ("success", [])

    def test_in_progress_pending(self) -> None:
        runs = [self._run("静态检查 + 单元测试"), self._run("构建 Docker 基础镜像", status="in_progress")]
        status, details = evaluate_check_runs(runs)
        assert status == "pending"
        assert details == ["构建 Docker 基础镜像"]

    def test_failed(self) -> None:
        runs = [self._run("静态检查 + 单元测试"), self._run("构建 Docker 基础镜像", conclusion="failure")]
        status, details = evaluate_check_runs(runs)
        assert status == "failure"
        assert details == ["构建 Docker 基础镜像"]


class TestGitHubApi:
    """GitHub REST API 客户端（httpx MockTransport）。"""

    @staticmethod
    def _transport() -> MockTransport:
        def handler(request: Request) -> Response:
            path = request.url.path
            if path.endswith("/pulls") and request.method == "GET":
                # find_pull：head=dev 返回已合并 PR，其他 head 返回空列表
                if request.url.params.get("head") == "dev":
                    return Response(200, json=[{"number": 7, "state": "merged"}])
                return Response(200, json=[])
            if path.endswith("/pulls/7/commits") and request.method == "GET":
                return Response(200, json=[
                    {"commit": {"message": "feat!: 重构三层结构"}},
                    {"commit": {"message": "fix: 修复问题"}},
                ])
            if path.endswith("/pulls") and request.method == "POST":
                head = json.loads(request.content)["head"]
                if head == "release/v0.4.0":
                    # 403：pull_request 事件下用 GITHUB_TOKEN 创建 PR 的典型拒绝
                    return Response(403, json={"message": "Resource not accessible by integration"})
                if head == "release/v0.5.0":
                    return Response(422, json={"message": "Validation Failed", "errors": [{"field": "head"}]})
                return Response(201, json={"number": 42})
            if path.endswith("/commits/abc123/check-runs") and request.method == "GET":
                return Response(200, json={"check_runs": [{"name": "CI", "status": "completed", "conclusion": "success"}]})
            if path.endswith("/pulls/42/merge") and request.method == "PUT":
                return Response(200, json={"merged": True})
            if path.endswith("/git/refs/heads/release/v0.2.0") and request.method == "DELETE":
                return Response(204)
            if path.endswith("/git/refs/heads/release/v0.6.0") and request.method == "DELETE":
                return Response(500, json={"message": "Internal Server Error"})
            if path.endswith("/pulls/99/merge") and request.method == "PUT":
                return Response(405, json={"message": "Pull request is not mergeable"})
            return Response(404)

        return MockTransport(handler)

    def _api(self) -> GitHubApi:
        return GitHubApi("test-token", "flower-star-dream", "flower-web-infrastructure", transport=self._transport())

    def test_create_pull(self) -> None:
        assert self._api().create_pull("chore(release): 发布正式版 v0.2.0", "release/v0.2.0", "main", "自动发版") == 42

    def test_create_pull_403_raises_with_hint(self) -> None:
        # 403 应附带 RELEASE_TOKEN / GITHUB_TOKEN 限制提示，便于 CI 排障
        with pytest.raises(httpx.HTTPStatusError) as exc:
            self._api().create_pull("chore(release): 发布正式版 v0.4.0", "release/v0.4.0", "main", "自动发版")
        assert "403" in str(exc.value)
        assert "RELEASE_TOKEN" in str(exc.value)

    def test_create_pull_error_includes_body(self) -> None:
        # 非 403 错误也应携带响应体正文（422 Validation Failed）
        with pytest.raises(httpx.HTTPStatusError) as exc:
            self._api().create_pull("chore(release): 发布正式版 v0.5.0", "release/v0.5.0", "main", "自动发版")
        assert "Validation Failed" in str(exc.value)

    def test_list_check_runs(self) -> None:
        runs = self._api().list_check_runs("abc123")
        assert runs == [{"name": "CI", "status": "completed", "conclusion": "success"}]

    def test_find_pull(self) -> None:
        assert self._api().find_pull(base="main", head="dev") == 7

    def test_find_pull_not_found(self) -> None:
        assert self._api().find_pull(base="main", head="feature/x") is None

    def test_list_pull_commits(self) -> None:
        commits = self._api().list_pull_commits(7)
        assert commits == ["feat!: 重构三层结构", "fix: 修复问题"]

    def test_merge_pull(self) -> None:
        self._api().merge_pull(42, method="squash")

    def test_merge_pull_not_mergeable_raises(self) -> None:
        with pytest.raises(RuntimeError, match="不可合并"):
            self._api().merge_pull(99, method="squash")

    def test_delete_branch(self) -> None:
        self._api().delete_branch("release/v0.2.0")

    def test_delete_branch_error_includes_body(self) -> None:
        # 500 错误应携带响应体正文，便于排障
        with pytest.raises(httpx.HTTPStatusError) as exc:
            self._api().delete_branch("release/v0.6.0")
        assert "Internal Server Error" in str(exc.value)


class TestCleanStaleReleaseBranch:
    """远端遗留 release 分支清理（上次运行失败残留，避免 non-fast-forward）。"""

    @staticmethod
    def _monkeypatch_git(monkeypatch: pytest.MonkeyPatch, results: dict[tuple[str, ...], str]) -> list[list[str]]:
        """替换 git 执行器：按命令元组返回预设 stdout，并记录调用。"""

        calls: list[list[str]] = []

        def fake_git(args: list[str], repo_root: Path) -> str:
            calls.append(args)
            return results.get(tuple(args), "")

        monkeypatch.setattr("release_after_merge.git", fake_git)
        return calls

    def test_branch_exists_deletes_then_push(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 远端存在同名分支：先 delete 再返回（后续正常推送）
        calls = self._monkeypatch_git(monkeypatch, {
            ("ls-remote", "--heads", "origin", "release/v0.1.1"): "abc123\trefs/heads/release/v0.1.1\n",
        })
        _clean_stale_release_branch(Path("."), "release/v0.1.1")
        assert ["ls-remote", "--heads", "origin", "release/v0.1.1"] in calls
        assert ["push", "origin", "--delete", "release/v0.1.1"] in calls

    def test_branch_not_exists_no_delete(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 远端无同名分支：仅探测，不删除
        calls = self._monkeypatch_git(monkeypatch, {})
        _clean_stale_release_branch(Path("."), "release/v0.2.0")
        assert calls == [["ls-remote", "--heads", "origin", "release/v0.2.0"]]


class TestEnsureAndPushTag:
    """正式版本 tag 推送（触发 ci.yml 正式版镜像发布）。"""

    @staticmethod
    def _monkeypatch_git(monkeypatch: pytest.MonkeyPatch, results: dict[tuple[str, ...], str]) -> list[list[str]]:
        """替换 git 执行器：按命令元组返回预设 stdout，并记录调用。"""

        calls: list[list[str]] = []

        def fake_git(args: list[str], repo_root: Path) -> str:
            calls.append(args)
            return results.get(tuple(args), "")

        monkeypatch.setattr("release_after_merge.git", fake_git)
        return calls

    def test_tag_not_exists_push(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 远端无同名 tag：探测后打 tag 并推送
        calls = self._monkeypatch_git(monkeypatch, {})
        ensure_and_push_tag(Path("."), "0.2.0")
        assert ["ls-remote", "--tags", "origin", "v0.2.0"] in calls
        assert ["tag", "v0.2.0"] in calls
        assert ["push", "origin", "v0.2.0"] in calls

    def test_tag_exists_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 远端已存在同名 tag（上次推送成功但后续步骤失败）：仅探测，不重复打 tag/推送
        calls = self._monkeypatch_git(monkeypatch, {
            ("ls-remote", "--tags", "origin", "v0.1.1"): "abc123\trefs/tags/v0.1.1\n",
        })
        ensure_and_push_tag(Path("."), "0.1.1")
        assert calls == [["ls-remote", "--tags", "origin", "v0.1.1"]]


class TestWaitForChecks:
    """等待检查轮询。"""

    class _FakeApi:
        """可控的假 GitHubApi：按序返回预设的 check runs。"""

        def __init__(self, responses: list[list[dict]]) -> None:
            self._responses = responses
            self.calls = 0

        def list_check_runs(self, sha: str) -> list[dict]:
            self.calls += 1
            if len(self._responses) == 1:
                return self._responses[0]
            return self._responses[min(self.calls - 1, len(self._responses) - 1)]

    @staticmethod
    def _run(name: str, status: str = "completed", conclusion: str = "success") -> dict:
        return {"name": name, "status": status, "conclusion": conclusion}

    def test_wait_until_success(self) -> None:
        api = self._FakeApi([
            [self._run("CI", status="in_progress")],
            [self._run("CI")],
        ])
        wait_for_checks(api, "abc", timeout_seconds=30, interval_seconds=0)
        assert api.calls == 2

    def test_immediate_success(self) -> None:
        api = self._FakeApi([[self._run("CI")]])
        wait_for_checks(api, "abc", timeout_seconds=30, interval_seconds=0)
        assert api.calls == 1

    def test_failure_raises(self) -> None:
        api = self._FakeApi([[self._run("CI", conclusion="failure")]])
        with pytest.raises(RuntimeError, match="CI 检查失败"):
            wait_for_checks(api, "abc", timeout_seconds=30, interval_seconds=0)

    def test_timeout_raises(self) -> None:
        api = self._FakeApi([[self._run("CI", status="in_progress")]])
        start = time.monotonic()
        with pytest.raises(TimeoutError, match="超时"):
            wait_for_checks(api, "abc", timeout_seconds=1, interval_seconds=0)
        assert time.monotonic() - start < 5
