# flower web 通用框架 CI/CD 文档

> 本文档说明本项目的持续集成（CI）与持续交付（CD）流水线：触发时机、流水线结构、门禁策略、本地复现与镜像推送开启方式。

- 工作流文件：[`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
- 平台：GitHub Actions
- 关联文件：`Dockerfile`、`.dockerignore`

## 1. 触发时机

| 事件 | 分支/范围 | 说明 |
| ---- | ---- | ---- |
| `push` | `main` | 合并到主干后运行全量流水线 |
| `pull_request` | 任意 | PR 提交/更新时运行，作为合入门禁 |

## 2. 流水线结构

流水线包含两个 Job，`build-image` 依赖 `test`（测试失败则不构建镜像）：

```
CI
├── test          (静态检查 + 单元测试)
└── build-image   (Docker 基础镜像构建 + 冒烟验证 + 按需推送)  needs: test
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
| 构建基础镜像 | `docker build -t flower-web-infrastructure:ci .`，基于 `Dockerfile`（整改 S20-2 多阶段构建：build 阶段安装依赖，runtime 阶段仅拷贝 site-packages + 源码） |
| 镜像漏洞扫描 | Trivy 扫描（`HIGH,CRITICAL`，`exit-code=1`），存在高危/严重漏洞即阻断（规范 §20.2） |
| 镜像签名 | cosign 签名（规范 §20.4 供应链防篡改）：`COSIGN_PRIVATE_KEY` 已配置时对 `flower-web-infrastructure:ci` 签名；密钥缺失自动跳过不阻断。正式版发布必须启用签名，且部署侧配套 `cosign verify` 校验后才拉取镜像（详见 ci.yml 对应步骤注释） |
| 冒烟验证 | 启动容器并轮询 `GET /health/live`（30 次 × 1s，存活探针，整改 S19-1），失败时输出容器日志 |
| 推送镜像（可选） | 默认注释关闭，见 [4. 镜像推送开启方式](#4-镜像推送开启方式) |

## 3. 门禁策略

| 检查项 | 门禁级别 | 说明 |
| ---- | ---- | ---- |
| 单元测试（pytest） | 硬性 | 失败即阻断合并与镜像构建 |
| 代码行覆盖率（pytest-cov） | 硬性 | `--cov-fail-under=70`：低于 70% 即阻断（规范 §11.2） |
| 静态类型检查（pyright） | 软性 | 既有 16 项基线错误不阻塞；新增代码须本地保持 0 错误（本地门禁） |
| 镜像漏洞扫描（Trivy） | 硬性 | 存在高危/严重漏洞即阻断镜像留存（规范 §20.2） |
| 镜像签名（cosign） | 正式版硬性 | `COSIGN_PRIVATE_KEY` 未配置时自动跳过；正式版发布必须启用并部署侧 `cosign verify`（规范 §20.4） |
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

## 4. 镜像推送开启方式

工作流默认只构建与冒烟验证镜像，不推送。需要推送到容器仓库时，取消 `build-image` Job 末尾注释并按以下步骤配置：

1. **选择仓库**：默认示例为 GitHub Container Registry（`ghcr.io`），可替换为 Docker Hub / 私有 Registry。
2. **登录认证**：
   - GHCR：使用 `secrets.GITHUB_TOKEN`（仓库默认可用，无需额外配置 Secret）；
   - Docker Hub 等第三方：需在仓库 Settings → Secrets 中配置用户名与访问令牌。
3. **推送标签规范**（整改 S20-3，`ghcr.io/<org>/<repo>` 命名）：
   - **测试版**（非正式发布，如 PR/分支构建）：`<分支名>-<时间戳>-<构建号>`，例如 `feature-login-20260815120000-42`；
   - **正式版**：语义化版本（SemVer），例如 `1.2.3`（与 `pyproject.toml` 版本号保持一致）；
   - **`latest`**：仅限最新正式版，禁止用测试构建覆盖。

   ```yaml
   IMAGE=ghcr.io/${{ github.repository }}
   # 测试版（分支名-时间戳-构建号）
   docker tag flower-web-infrastructure:ci $IMAGE:${{ github.ref_name }}-$(date +%Y%m%d%H%M%S)-${{ github.run_number }}
   docker push $IMAGE:${{ github.ref_name }}-$(date +%Y%m%d%H%M%S)-${{ github.run_number }}
   # 正式版（SemVer，仅版本发布时打）
   # docker tag flower-web-infrastructure:ci $IMAGE:1.2.3
   # docker push $IMAGE:1.2.3
   # latest 仅限最新正式版
   # docker tag flower-web-infrastructure:ci $IMAGE:latest
   # docker push $IMAGE:latest
   ```

   > 说明：CI 内部构建标签固定为 `flower-web-infrastructure:ci`，仅用于流水线内构建/扫描/冒烟，不对外推送；对外推送遵循上述标签规范。

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
- **与 CI 联动**：按 [4. 镜像推送开启方式](#4-镜像推送开启方式) 的标签规范打 tag；建议 dev/test/stage 的构建 tag（`<分支名>-<时间戳>-<构建号>`）与 prod 的 SemVer tag 前缀区分，便于仓库按 tag 规则过滤保留。

## 6. 维护指南

| 场景 | 操作位置 |
| ---- | ---- |
| 调整触发分支 | `ci.yml` 中 `on.push.branches` |
| 升级 Python 版本 | `ci.yml` 中 `setup-python.python-version`，同步修改 `Dockerfile` 基础镜像与 `pyproject.toml` 的 `requires-python` |
| 新增依赖 | 修改 `pyproject.toml` 的 `dependencies` / `optional-dependencies` |
| 新增检查（如代码覆盖率） | 在 `test` Job 追加步骤，并明确门禁级别 |
| 修改镜像内容 | 编辑 `Dockerfile`，注意 `HEALTHCHECK` 依赖 `/health/live` 存活端点（整改 S19-1）；就绪探测 `/health/ready` 由编排层配置 |
| 版本发布 | 遵循 SemVer，同步更新 `pyproject.toml` 与 `README.md` 版本号 |

## 7. 常见问题

- **pytest 失败**：`test` Job 中断，镜像不构建。按 `pytest` 输出定位失败用例，修复后重新推送/更新 PR。
- **冒烟验证超时**：容器 30 秒内 `/health/live` 不可达。查看 Job 输出的 `docker logs`，常见原因：依赖安装缺失、启动端口被占、`application.default.yml` 配置异常。
- **pyright 报新增错误**：不阻塞流水线，但应在本地修复（`pyright` 输出定位），保持新增代码 0 错误。
