# flower web 通用框架 CI/CD 文档

> 本文档说明本项目的持续集成（CI）与持续交付（CD）流水线：触发时机、流水线结构、门禁策略、本地复现与镜像推送开启方式。

- 工作流文件：[`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
- 平台：GitHub Actions
- 关联文件：`Dockerfile`、`.dockerignore`

## 1. 触发时机

| 事件 | 分支/范围 | 说明 |
| ---- | ---- | ---- |
| `push` | `main` | 合并到主干后运行全量流水线，并推送测试标签镜像（含 `latest`） |
| `push` | `dev` | 开发分支推送即运行全量验证（test + 镜像构建/漏洞扫描/冒烟），**不推送**镜像；保证 CI 通过后再提 PR |
| `push` | `v*` 版本 tag | 打版本标签时运行全量流水线，并推送正式版镜像（SemVer + `latest`）。受 `paths-ignore` 过滤：tag 指向的提交仅含文档/非代码变更（`*.md`、`docs/**` 等）时跳过；正式发版提交必然修改 `pyproject.toml`，不受影响 |
| `pull_request` | 任意 | PR 提交/更新时运行，作为合入门禁；只构建/扫描/冒烟，**不推送**镜像 |

> **非代码变更不触发**（`push` main / dev、`push` tag 与 PR 均生效）：仅修改文档与非代码文件（`*.md`、`docs/**`、`LICENSE`、`.gitignore`、`.env.example`、`db/**`、`data/**`）时不运行流水线；这些变更不参与单元测试与镜像构建。正式发版 tag 指向的提交必然修改 `pyproject.toml`，故实际不会跳过。

## 2. 流水线结构

流水线包含两个 Job，`build-image` 依赖 `test`（测试失败则不构建镜像）：

```
CI
├── test          (静态检查 + 单元测试)
└── build-image   (Docker 基础镜像构建 + 漏洞扫描 + 签名 + 冒烟 + 推送 GHCR)  needs: test
```

### 2.1 test —— 静态检查 + 单元测试

运行环境：`ubuntu-latest`，Python 3.11。

| 步骤 | 命令 | 行为 |
| ---- | ---- | ---- |
| 检出代码 | `actions/checkout@v4` | 拉取仓库代码 |
| 安装 Python | `actions/setup-python@v5` | Python 3.11，启用 pip 缓存 |
| 安装依赖 | `pip install -e ".[dev]"` | 安装框架本体 + dev 依赖（pytest / pytest-cov / pytest-asyncio / pyright） |
| 静态类型检查 | `pyright` | `continue-on-error: true`：容忍既有基线错误，不阻塞流水线 |
| 单元测试 + 覆盖率 | `pytest -q --cov=web_infra --cov-fail-under=70` | 硬性门禁：任一失败即中断流水线；行覆盖率 < 70% 亦中断（规范 §11.2） |

### 2.2 build-image —— Docker 基础镜像构建与验证

| 步骤 | 行为 |
| ---- | ---- |
| 构建基础镜像 | `docker build -t flower-web-infrastructure:ci .`，基于 `Dockerfile`（整改 S20-2 多阶段构建：build 阶段安装依赖 `min-monolith + migrate` extras，runtime 阶段仅拷贝 site-packages + 源码，并清理基础镜像自带构建期工具 pip/setuptools/wheel——消除 Trivy 高危漏洞，如 setuptools 内置 wheel/jaraco.context、pip 内置 setuptools/msgpack） |
| 镜像漏洞扫描 | Trivy 扫描（`HIGH,CRITICAL`，`exit-code=1`），存在高危/严重漏洞即阻断（规范 §20.2） |
| 镜像签名 | cosign **keyless（OIDC）** 签名（规范 §20.4 供应链防篡改）：使用 GitHub Actions OIDC 身份自动签名（Job 声明 `id-token: write`），**无需配置密钥/Secret**；镜像先推送 GHCR 再签名（cosign 只能签名仓库中的镜像，本地 `:ci` 标签会被解析到 Docker Hub 导致 401），签名绑定镜像 digest，同一 digest 的多个 tag（main-xxx / SemVer / latest）分别签名。部署侧必须配套 `cosign verify` 校验签名后才拉取镜像（校验命令见 §8） |
| 冒烟验证 | 启动容器并轮询 `GET /health/live`（30 次 × 1s，存活探针，整改 S19-1），失败时输出容器日志 |
| 推送镜像（GHCR） | 已启用：push `main` 推测试标签 + `latest`；版本 tag `v*` 推 SemVer + `latest`；PR 不推送。详见 [4. 镜像推送](#4-镜像推送已启用) |

## 3. 门禁策略

| 检查项 | 门禁级别 | 说明 |
| ---- | ---- | ---- |
| 单元测试（pytest） | 硬性 | 失败即阻断合并与镜像构建 |
| 代码行覆盖率（pytest-cov） | 硬性 | `--cov-fail-under=70`：低于 70% 即阻断（规范 §11.2） |
| 静态类型检查（pyright） | 软性 | 既有 16 项基线错误不阻塞；新增代码须本地保持 0 错误（本地门禁） |
| 镜像漏洞扫描（Trivy） | 硬性 | 存在高危/严重漏洞即阻断镜像留存（规范 §20.2） |
| 镜像签名（cosign keyless） | 硬性 | 基于 GitHub Actions OIDC 身份签名，无需密钥；部署侧必须 `cosign verify`（OIDC issuer / identity 匹配）通过后才拉取镜像（规范 §20.4） |
| 镜像构建 + `/health/live` 冒烟 | 硬性 | 基础镜像必须可启动且存活探针通过（整改 S19-1：就绪探测 `/health/ready` 由编排层使用） |

### 3.1 本地复现

在提交前执行与 CI 相同的检查：

```bash
# 安装依赖
.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 静态类型检查
.venv\Scripts\pyright.exe

# 单元测试 + 覆盖率门禁（与 CI 一致）
.venv\Scripts\python.exe -m pytest --cov=web_infra --cov-fail-under=70

# 镜像构建与冒烟（本机需安装 Docker）
docker build -t flower-web-infrastructure:ci .
docker run -d --name web-infra-smoke -p 18000:8000 flower-web-infrastructure:ci
curl http://127.0.0.1:18000/health/live
docker rm -f web-infra-smoke
```

## 4. 镜像推送（已启用）

工作流已启用 GHCR 推送（镜像地址 `ghcr.io/flower-star-dream/flower-web-infrastructure`）。登录使用 `secrets.GITHUB_TOKEN`（仓库默认可用，无需额外配置 Secret；`build-image` Job 已声明 `permissions: packages: write`）。CI 内部构建标签固定为 `flower-web-infrastructure:ci`，仅用于流水线内构建/扫描/冒烟，不对外推送。

**推送标签规范**（整改 S20-3，`ghcr.io/<org>/<repo>` 命名）：

| 触发 | 推送标签 | 说明 |
| ---- | ---- | ---- |
| push `main` | `main-<时间戳>-<构建号>` | 测试版，如 `main-20260816103000-42` |
| push `main` | `latest` | **跟随最新 main 构建**：脚手架等下游 CI 拉取 `:latest` 作为业务镜像基础（见脚手架 CI/CD 文档） |
| 版本 tag `v*` | `<SemVer>` | 正式版，如 tag `v0.1.0-dev4` → 推送 `0.1.0-dev4`（与 `pyproject.toml` 版本号保持一致） |
| 版本 tag `v*` | `latest` | 正式版发布时覆盖为最新正式版 |
| PR | 不推送 | 只构建/扫描/冒烟，避免测试镜像污染仓库 |

> 说明：`latest` 策略为"跟随最新 main 构建，正式版发布时覆盖为正式版"（2026-08-16 起与脚手架 CI 联动，替代原"latest 仅限正式版"约定）。

## 5. 镜像保留与清理

> 规范 §20.5：镜像保留策略 + 悬空清理 + 回收审计属**运维配置**（框架边界），CI 负责按标签规范推送，仓库侧保留规则与清理任务由运维按环境配置。以下为本项目建议基线，业务按容量与发布频率调整：

| 环境 | 保留建议 |
| ---- | ---- |
| dev | 保留最近 **10** 个镜像 |
| test | 保留最近 **20** 个镜像 |
| stage | 保留最近 **50** 个镜像 |
| prod | **永久保留** + 按版本 tag 保留（SemVer tag 不清理；`latest` 跟随最新正式版） |

- **悬空镜像清理**：每周执行一次（建议周一凌晨低峰期），清理未被任何 tag 引用的悬空镜像（dangling images）与过期构建层。
- **回收审计**：每次清理输出清理清单（镜像 ID / tag / 创建时间 / 大小）与**回收体积**（GB），归档至运维日志，便于追溯误删与容量趋势分析。
- **保留策略配置入口**：
  - **GitHub Packages（ghcr.io）**：Settings → Packages → 选择镜像包 → 设置保留策略（"保留最近 N 个版本"）；也可用 `actions/ghcr-packages-deletion` 类工作流按 tag 规则定期清理。
  - **Harbor**：项目 → 镜像仓库 → 配置"回收策略"（保留最近 N 个 / 按 tag 规则）+ "垃圾回收"（悬空层清理）定时任务，并开启回收审计日志。
  - **Docker Hub**：Repository → Tags → 保留策略（保留最近 N 个 tag）。
- **与 CI 联动**：按 [4. 镜像推送](#4-镜像推送已启用) 的标签规范打 tag；dev/test/stage 的构建 tag（`main-<时间戳>-<构建号>`）与 prod 的 SemVer tag 前缀区分，便于仓库按 tag 规则过滤保留；`latest` 始终被下游依赖，不应配置过期清理。

## 6. 维护指南

| 场景 | 操作位置 |
| ---- | ---- |
| 调整触发分支 | `ci.yml` 中 `on.push.branches` |
| 升级 Python 版本 | `ci.yml` 中 `setup-python.python-version`，同步修改 `Dockerfile` 基础镜像与 `pyproject.toml` 的 `requires-python` |
| 新增依赖 | 修改 `pyproject.toml` 的 `dependencies` / `optional-dependencies` |
| 新增检查（如代码覆盖率） | 在 `test` Job 追加步骤，并明确门禁级别 |
| 修改镜像内容 | 编辑 `Dockerfile`，注意 `HEALTHCHECK` 依赖 `/health/live` 存活端点（整改 S19-1）；就绪探测 `/health/ready` 由编排层配置 |
| 版本发布 | dev→main 走 PR 合入：release workflow 自动发版并打 `v<版本>` tag（触发正式版镜像推送 SemVer + `latest`）；直接提交 main / 本地合入场景手动打 `v<版本>` tag（需与 `pyproject.toml` 版本号一致） |
| 变更推送策略（如目标仓库） | `build-image` Job 的登录与推送步骤，同步更新本文档 [4. 镜像推送](#4-镜像推送已启用) |
| 配置/变更 Secret 或包权限 | 见 [8. 仓库配置（Settings / Secrets）](#8-仓库配置settings--secrets) |

## 7. 常见问题

- **pytest 失败**：`test` Job 中断，镜像不构建。按 `pytest` 输出定位失败用例，修复后重新推送/更新 PR。
- **Trivy 扫描失败（高危/严重漏洞）**：镜像漏洞扫描失败会阻断镜像留存（`exit-code=1`）。历史根因：基础镜像 `python:3.11-slim` 自带构建期工具（pip/setuptools/wheel 及其 vendored 依赖）被整包带入 runtime 层（如 setuptools 内置 wheel 0.45.1 / jaraco.context 5.3.0、pip 内置 setuptools 70.3.0 / msgpack 1.1.2）。Dockerfile 已做两处清理：build 阶段卸载构建期工具、runtime 阶段删除基础镜像自带残留；若后续新增 Python 依赖引入新的高危漏洞，升级依赖版本后重新构建即可。
- **冒烟验证超时**：容器 30 秒内 `/health/live` 不可达。查看 Job 输出的 `docker logs`，常见原因：依赖安装缺失、启动端口被占、`application.default.yml` 配置异常。
- **pyright 报新增错误**：不阻塞流水线，但应在本地修复（`pyright` 输出定位），保持新增代码 0 错误。
- **GHCR 推送失败（403 / denied）**：确认 `build-image` Job 的 `permissions.packages: write` 已声明；首次推送时需在 GitHub Settings → Packages 中授权该镜像包（Package visibility 至少设为 private，并为本组织成员配置读权限）。
- **keyless 签名失败（OIDC token / 5xx）**：确认 `build-image` Job 的 `permissions.id-token: write` 已声明；签名需要访问 `token.actions.githubusercontent.com` 与 Rekor 日志服务，自托管 runner / 受限网络需放行这两个域名。
- **自动发版失败（创建 PR 403 Forbidden）**：release workflow 创建发版 PR 被 403 拒绝（`Resource not accessible by integration`）。根因：流程使用了默认 `GITHUB_TOKEN`——`pull_request` 事件下用其创建 PR 常被 403，且其创建的 PR 不会触发 CI（`wait_for_checks` 必超时）。修复：在仓库 Secrets 配置 `RELEASE_PAT`（经典 PAT，勾选 `repo` scope），workflow 已改为 checkout 与脚本均使用该 PAT。
- **自动发版失败（推送 release 分支 non-fast-forward）**：`git push origin release/vX.Y.Z` 被拒（`[rejected] ... (non-fast-forward)`）。原因：上次运行失败遗留同名远端分支（如推送成功但创建 PR 失败），本次基于更新后的 main 重建同名分支，历史不一致被拒。脚本已自动处理：推送前用 `git ls-remote` 探测同名分支，存在则先 `git push --delete` 清理再推送，可重复执行；无需人工干预。

## 8. 仓库配置（Settings / Secrets）

流水线所需配置项一览。`GITHUB_TOKEN` 由 GitHub 自动注入（`build-image` Job 已声明 `packages: write`，GHCR 登录/推送无需额外配置）；镜像签名采用 **cosign keyless（OIDC）**，基于 GitHub Actions 的 OIDC 身份（`id-token: write` 权限已在 ci.yml 声明），**无需配置任何密钥/Secret**。Secret 名称必须与 `ci.yml` 中的引用（`secrets.XXX`）完全一致。

| 配置项 | 类型 | 配置位置 | 必需性 | 用途与说明 |
| ---- | ---- | ---- | ---- | ---- |
| 镜像包可见性与权限 | 包设置 | 本仓库 Settings → Packages → flower-web-infrastructure | 首次推送后配置 | 首次 CI 推送成功后在 GitHub 生成镜像包，设置可见性（public/private）与成员读权限。**私有包拉取方**（如脚手架仓库 CI、部署环境）需在包设置中授权读权限 |
| `GITHUB_TOKEN` | 自动注入 | 无需配置 | — | GHCR 登录与推送凭据（`packages: write` 已在 ci.yml 声明） |
| `RELEASE_PAT` | 仓库 Secret | Settings → Secrets and variables → Actions | **发版必需** | 自动发版（release.yml）专用经典 PAT，勾选 `repo` scope（contents + pull_requests 写权限）。**不能用默认 GITHUB_TOKEN**：GitHub 规定其创建 PR / 推送不触发新的 workflow run（发版 PR 无法触发 CI），且 `pull_request` 事件下创建 PR 常被 403 拒绝。配置步骤见 §13.1.1（README） |
| OIDC 身份（keyless 签名） | 自动注入 | 无需配置 | — | `id-token: write` 权限已在 ci.yml 声明，cosign 自动获取 Actions OIDC token 签名 |

**镜像签名与校验**（规范 §20.4）：

- CI 侧：镜像先推送 GHCR 再签名——`cosign sign --yes ghcr.io/flower-star-dream/flower-web-infrastructure:<推送的标签>`（cosign v2 默认 keyless，`sigstore/cosign-installer@v3` 安装；不能签名未推送的本地镜像，如 `flower-web-infrastructure:ci` 会被解析到 Docker Hub 报 401）。
- 部署侧（拉取镜像前必须校验签名）：`cosign verify --certificate-oidc-issuer https://token.actions.githubusercontent.com --certificate-identity-regexp "https://github.com/flower-star-dream/flower-web-infrastructure/.github/workflows/ci.yml@refs/.*" ghcr.io/flower-star-dream/flower-web-infrastructure:<版本>`

**配置顺序建议**（首次接入时按序执行）：

1. 推送本仓库 `main`，确认流水线通过、镜像已签名并推送；
2. 到 Settings → Packages 设置镜像包可见性（private 时为本组织成员配置读权限）；
3. （如需脚手架跨仓库拉取）在包设置中授权脚手架仓库或设为 public（见脚手架 CI/CD 文档 §9）。
