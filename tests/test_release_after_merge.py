"""自动发版脚本单元测试

@Author: 花海
@Date: 2026/08/17 22:00
@Description: 覆盖 scripts/release_after_merge.py 的正式版本计算规则（dev→main 合入发版）、
              git remote 解析、check runs 评估、GitHub API 客户端（httpx MockTransport）
              与等待检查轮询逻辑。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from httpx import MockTransport, Request, Response

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from release_after_merge import (  # noqa: E402
    GitHubApi,
    evaluate_check_runs,
    parse_repo_remote,
    release_version,
    wait_for_checks,
)
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
            if path.endswith("/pulls") and request.method == "POST":
                return Response(201, json={"number": 42})
            if path.endswith("/commits/abc123/check-runs") and request.method == "GET":
                return Response(200, json={"check_runs": [{"name": "CI", "status": "completed", "conclusion": "success"}]})
            if path.endswith("/pulls/42/merge") and request.method == "PUT":
                return Response(200, json={"merged": True})
            if path.endswith("/git/refs/heads/release/v0.2.0") and request.method == "DELETE":
                return Response(204)
            if path.endswith("/pulls/99/merge") and request.method == "PUT":
                return Response(405, json={"message": "Pull request is not mergeable"})
            return Response(404)

        return MockTransport(handler)

    def _api(self) -> GitHubApi:
        return GitHubApi("test-token", "flower-star-dream", "flower-web-infrastructure", transport=self._transport())

    def test_create_pull(self) -> None:
        assert self._api().create_pull("chore(release): 发布正式版 v0.2.0", "release/v0.2.0", "main", "自动发版") == 42

    def test_list_check_runs(self) -> None:
        runs = self._api().list_check_runs("abc123")
        assert runs == [{"name": "CI", "status": "completed", "conclusion": "success"}]

    def test_merge_pull(self) -> None:
        self._api().merge_pull(42, method="squash")

    def test_merge_pull_not_mergeable_raises(self) -> None:
        with pytest.raises(RuntimeError, match="不可合并"):
            self._api().merge_pull(99, method="squash")

    def test_delete_branch(self) -> None:
        self._api().delete_branch("release/v0.2.0")


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
