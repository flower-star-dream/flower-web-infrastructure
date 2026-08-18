"""版本计算与同步核心库（release workflow 使用）

@Author: 花海
@Date: 2026/08/17 21:10
@Description: release-only 版本机制（2026-08-18 整改）下的版本计算核心：
              本地提交不再自动递增版本号（git 限制：pre-commit 拿不到提交消息无法按类型递增，
              prepare-commit-msg/commit-msg 中修改 index 不进本次提交），版本递增统一由
              dev→main 合入时的 release workflow 完成（scripts/release_after_merge.py 调用本模块）。
              本模块提供：提交类型解析（parse_commit_type）、版本递增计算（release_version /
              bump_version）、版本文件同步（write_version，同步 pyproject.toml /
              src/web_infra/__init__.py / README / docs 版本引用）。
              版本号遵循语义化版本规范（SemVer，https://semver.org/lang/zh-CN/）：X.Y.Z 正式版，
              预发布用连字符 -devN（同时兼容 PEP 440，pip 安装时归一化处理）。
              本地版本一致性校验与暂存见 scripts/version_check.py（pre-commit 钩子）。
"""

from __future__ import annotations

import re
import subprocess
from enum import Enum
from pathlib import Path

# 版本号：X.Y.Z 或 X.Y.Z-devN（SemVer 规范；预发布版本用连字符 - 连接，MAJOR/MINOR/PATCH
# 为非负整数且禁止前导零，如 01.2.3 / 1.02.3 / 1.2.03 均非法；-devN 兼容 PEP 440，
# pip 安装时归一化为 X.Y.Z.devN）
_VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-dev(?P<dev>\d+))?$"
)

# pyproject.toml 中 version = "..."（仅 [project] 段首处）
_PYPROJECT_VERSION_RE = re.compile(r'(?m)^version\s*=\s*"[^"]*"')

# __init__.py 中 __version__ = "..."
_INIT_VERSION_RE = re.compile(r'(?m)^__version__\s*=\s*"[^"]*"')

# conventional commits 前缀（支持 scope，如 feat(auth): xxx；前缀大小写不敏感）
_TYPE_RE = re.compile(
    r"^(?P<type>feat|fix|refactor|perf|test|build|ci|style|docs|chore)"
    r"(?:\((?P<scope>[^()]*)\))?"
    r"(?P<breaking>!)?:",
    re.IGNORECASE,
)

# 版本文件（相对仓库根）：代码与文档中展示框架当前版本的位置，随版本号自动同步
_VERSION_FILES = (
    "pyproject.toml",
    "src/web_infra/__init__.py",
    "README.md",
    "docs/CI-CD.md",
    "docs/使用说明.md",
)

# 文档中的框架当前版本引用（写入时用上下文精确匹配，避免误伤规则示例表、
# 数据库迁移版本 V0.2.0-*、业务版本号等；{v} 会被替换为当前（旧）版本号）
_DOC_VERSION_RULES: tuple[tuple[str, str], ...] = (
    ("README.md", r"version-v{v}(?=-blue)"),        # 徽章版本
    ("README.md", r"\| 当前版本 \| v{v}"),            # 项目信息表当前版本
    ("README.md", r"当前版本：\*\*v{v}\*\*"),         # §13 当前版本
    ("docs/CI-CD.md", r"tag `v{v}` → 推送 `v{v}`"),    # 镜像标签规范示例（v 前缀，规范 §20.1.1）
    ("docs/使用说明.md", r"@v{v}"),                    # Git 依赖安装示例
)

# 开发分支判定模式：精确匹配 dev，或 dev/、dev- 前缀，或 -dev 后缀
_DEV_BRANCH_PATTERNS = ("dev/", "dev-", "-dev")


class CommitType(Enum):
    """提交类型（决定版本递增策略）。"""

    SKIP = "skip"        # merge / revert / squash：跳过，不更新版本
    NO_CHANGE = "no_change"  # docs / chore / test / build / ci / style：文档/杂物/测试/构建/CI/格式，不更新版本
    BREAKING = "breaking"    # 破坏性变更：大版本 +1
    FEAT = "feat"            # 新功能：小版本 +1
    PATCH = "patch"          # 修复或其他小修改：补丁 +1


def parse_commit_type(subject: str, body: str = "", source: str = "") -> CommitType:
    """解析提交类型（含 scope / 破坏性标记）。

    :param subject: 提交信息第一行（主题）
    :param body: 提交信息其余内容（用于识别 BREAKING CHANGE footer）
    :param source: prepare-commit-msg 钩子的第二参数（提交信息来源）
    :return: CommitType
    """
    # merge / squash 提交信息无法解析前缀，直接跳过
    if source in ("merge", "squash") or subject.startswith("Merge "):
        return CommitType.SKIP
    # revert 提交不自动递增（版本应回到被还原前的语义，由人工处理）
    if subject.startswith("Revert "):
        return CommitType.SKIP

    full_text = f"{subject}\n{body}"
    breaking_footer = bool(re.search(r"BREAKING[ -]CHANGE\s*:", full_text, re.IGNORECASE))

    m = _TYPE_RE.match(subject.strip())
    if m is None:
        # 无标准前缀：视为"其他小修改"，按补丁处理（提示用户规范前缀）
        return CommitType.BREAKING if breaking_footer else CommitType.PATCH

    commit_type = m.group("type").lower()
    has_bang = m.group("breaking") == "!"
    if breaking_footer or has_bang:
        return CommitType.BREAKING
    # 不改变库行为的提交类型不更新版本（纯文档/杂物/测试/构建/CI/格式调整）
    if commit_type in ("docs", "chore", "test", "build", "ci", "style"):
        return CommitType.NO_CHANGE
    if commit_type == "feat":
        return CommitType.FEAT
    return CommitType.PATCH


def is_dev_branch(branch: str) -> bool:
    """判断分支是否为开发分支（打预发布版本号 -devN）。

    :param branch: 分支名（git branch --show-current）
    :return: True 表示开发分支
    """
    if not branch:
        return False
    return branch == "dev" or any(
        branch.startswith(p) or branch.endswith(p) for p in _DEV_BRANCH_PATTERNS
    )


def bump_version(current: str, commit_type: CommitType, branch: str) -> str | None:
    """根据提交类型与分支计算新版本号。

    :param current: 当前版本（X.Y.Z 或 X.Y.Z-devN）
    :param commit_type: 提交类型
    :param branch: 当前分支名
    :return: 新版本号；None 表示无需更新
    :raises ValueError: 当前版本号格式非法
    """
    if commit_type in (CommitType.SKIP, CommitType.NO_CHANGE):
        return None

    m = _VERSION_RE.match(current)
    if m is None:
        raise ValueError(f"无法解析版本号: {current!r}（期望 X.Y.Z 或 X.Y.Z-devN，SemVer 规范）")
    major, minor, patch = int(m.group("major")), int(m.group("minor")), int(m.group("patch"))
    dev = int(m.group("dev")) if m.group("dev") is not None else None

    # 开发分支：基础版本不动，仅递增/追加预发布版本号 -devN
    if is_dev_branch(branch):
        base = f"{major}.{minor}.{patch}"
        return f"{base}-dev{0 if dev is None else dev + 1}"

    # 正式分支：剥离 -devN（若有）后按提交类型递增基础版本
    if commit_type is CommitType.BREAKING:
        return f"{major + 1}.0.0"
    if commit_type is CommitType.FEAT:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def read_current_version(repo_root: Path) -> str:
    """从 pyproject.toml 读取当前版本（权威来源）。

    :param repo_root: 仓库根目录
    :return: 当前版本号
    :raises RuntimeError: pyproject.toml 中未找到 version 字段
    """
    text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    m = _PYPROJECT_VERSION_RE.search(text)
    if m is None:
        raise RuntimeError("pyproject.toml 中未找到 version 字段")
    return m.group(0).split('"')[1]


def _base_version(version: str) -> str:
    """提取版本号的基础部分（剥离 -devN 预发布后缀）。

    :param version: 完整版本号（X.Y.Z 或 X.Y.Z-devN）
    :return: 基础版本 X.Y.Z
    """
    m = _VERSION_RE.match(version)
    if m is None:
        raise ValueError(f"无法解析版本号: {version!r}")
    return f"{m.group('major')}.{m.group('minor')}.{m.group('patch')}"


def _bump_base(base: str, kind: str) -> str:
    """对基础版本 X.Y.Z 按类型递增（用于重算 README 演示示例的目标版本）。

    :param base: 基础版本 X.Y.Z
    :param kind: minor（小版本+1）/ patch（补丁+1）/ major（大版本+1）
    :return: 递增后的版本
    """
    major, minor, patch = (int(part) for part in base.split("."))
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _sync_readme_examples(text: str, old_version: str, new_version: str) -> str:
    """同步 README 规则示例表 / 开发分支示例 / 合入指南中的演示示例。

    演示示例以当前基础版本 X.Y.Z 为基数（如 `0.1.0` → `0.2.0` 的 feat 演示），
    随版本变化整体重算基数与目标（小版本目标 = 基数 minor+1、补丁目标 = 基数 patch+1、
    大版本目标 = 基数 major+1）。dev 分支基础版本不变时（如 0.1.0-dev0）示例不动。

    仅处理含示例特征的行（→ / -dev / tag v），跳过含 "V0." 的数据库迁移引用行，
    且要求行内出现当前基数（old_base）或其派生目标，避免误伤非示例内容。

    :param text: README 全文
    :param old_version: 当前（旧）版本号
    :param new_version: 新版本号
    :return: 同步后的 README 文本
    """
    old_base = _base_version(old_version)
    new_base = _base_version(new_version)
    if old_base == new_base:
        return text

    # 旧基数派生目标（示例行内可能出现）→ 新基数对应目标；值相同的键合并
    mapping: dict[str, str] = {old_base: new_base}
    for kind in ("patch", "minor", "major"):
        old_target = _bump_base(old_base, kind)
        mapping.setdefault(old_target, _bump_base(new_base, kind))
    pattern = re.compile("|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)))

    def _replace(m: re.Match[str]) -> str:
        return mapping[m.group(0)]

    trigger_tokens = ("→", "-dev", "tag v")
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if "V0." in line:
            continue  # 数据库迁移引用（V0.2.0-*）不随框架版本变化
        if not any(token in line for token in trigger_tokens):
            continue
        # tag 示例行（如 `git tag v0.2.0`）不含旧基数本身，按 old_minor 目标识别
        if old_base not in line and not ("tag v" in line and _bump_base(old_base, "minor") in line):
            continue
        lines[i] = pattern.sub(_replace, line)
    return "".join(lines)


def write_version(repo_root: Path, old_version: str, new_version: str) -> None:
    """同步更新 pyproject.toml、__init__.py 及文档中的框架版本号引用。

    :param repo_root: 仓库根目录
    :param old_version: 当前（旧）版本号，用于文档引用精确匹配
    :param new_version: 新版本号
    :raises RuntimeError: 代码版本字段未匹配到，已中止写入
    """
    pyproject_path = repo_root / "pyproject.toml"
    init_path = repo_root / "src" / "web_infra" / "__init__.py"

    text = pyproject_path.read_text(encoding="utf-8")
    updated, count = _PYPROJECT_VERSION_RE.subn(f'version = "{new_version}"', text, count=1)
    if count != 1:
        raise RuntimeError("pyproject.toml 中未匹配到 version 字段，已中止写入")
    pyproject_path.write_text(updated, encoding="utf-8")

    text = init_path.read_text(encoding="utf-8")
    updated, count = _INIT_VERSION_RE.subn(f'__version__ = "{new_version}"', text, count=1)
    if count != 1:
        raise RuntimeError("__init__.py 中未匹配到 __version__ 字段，已中止写入")
    init_path.write_text(updated, encoding="utf-8")

    # 文档中的当前版本展示（README 徽章/信息表/§13 与 docs 示例），按上下文精确匹配替换
    for rel_path, template in _DOC_VERSION_RULES:
        doc_path = repo_root / rel_path
        if not doc_path.exists():
            continue
        text = doc_path.read_text(encoding="utf-8")
        pattern = template.format(v=re.escape(old_version))
        updated, _ = re.subn(pattern, lambda m: m.group(0).replace(old_version, new_version), text)
        if updated != text:
            doc_path.write_text(updated, encoding="utf-8")

    # README 演示示例（规则示例表 / 开发分支示例 / 合入指南）以基础版本为基数整体重算
    readme_path = repo_root / "README.md"
    if readme_path.exists():
        text = readme_path.read_text(encoding="utf-8")
        updated = _sync_readme_examples(text, old_version, new_version)
        if updated != text:
            readme_path.write_text(updated, encoding="utf-8")


def git(args: list[str], repo_root: Path) -> str:
    """执行 git 命令并返回 stdout（去尾换行）。

    :param args: git 子命令参数
    :param repo_root: 仓库根目录（作为 cwd）
    :return: 命令标准输出
    """
    result = subprocess.run(
        ["git", *args], cwd=str(repo_root), capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {result.stderr.strip()}")
    return result.stdout.strip()
