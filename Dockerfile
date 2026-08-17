# =====================================================================
# flower-web-infrastructure 基础镜像（整改 S20-2：多阶段构建）
# @Author: 花海
# @Date: 2026/08/14 22:00
# @Description: 基础设施库基础镜像：安装 web_infra 依赖（min-monolith + migrate extras，含 MySQL/SQLite/Redis/Alembic）
#               并默认启动 create_app()（含 /health/live /health/ready /health /metrics），
#               业务项目通过 FROM 继承本镜像（挂载 application.yml 与业务代码后覆盖启动命令）。
#               构建分两阶段：build 阶段完成 pip 依赖安装；runtime 阶段仅拷贝 site-packages + 源码，产物更小更安全。
#               2026-08-16 整改：runtime 清理基础镜像自带构建期工具（pip/setuptools/wheel），消除 Trivy 高危漏洞阻断。
#               2026-08-17 整改：runtime 启动时 apt-get upgrade 升级系统包，消除基础镜像浮动标签
#               拉取到未修复快照导致的 Trivy 高危漏洞（CVE-2026-53615，util-linux 家族，修复版 2.41.5-0+deb13u1）。
# =====================================================================

# ---- build 阶段：安装依赖到系统 site-packages ----
# 基础镜像版本说明：当前使用 python:3.11-slim 浮动 patch 标签，建议在生产锁定具体 digest
# （docker pull python:3.11-slim && docker image inspect python:3.11-slim --format '{{index .RepoDigests 0}}'），
# 避免不可验证的版本漂移；不猜测具体 patch 号。
FROM python:3.11-slim AS build

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# 先复制依赖清单利用 Docker 层缓存，再复制源码安装
# 安装 extras：min-monolith（核心 + MySQL/SQLite + Redis）+ migrate（Alembic）——
# 与框架默认配置（application.default.yml 中 app.db.type=mysql）及单体业务（脚手架）运行需求一致；
# 业务项目 FROM 本镜像后无需再装数据库/缓存依赖。
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && \
    pip install ".[min-monolith,migrate]" && \
    # 清理构建期工具（Trivy 高危/严重阻断修复）：
    # pip 内置 setuptools 70.3.0 / msgpack 1.1.2、setuptools 内置 wheel 0.45.1 / jaraco.context 5.3.0
    # 均存在 HIGH 漏洞（CVE-2025-47273 / GHSA-6v7p-g79w-8964 / CVE-2026-24049 / CVE-2026-23949）；
    # 这些仅构建需要、运行时不需要，若不卸载会被整包拷贝进 runtime 层并导致 CI 的 Trivy 门禁失败。
    pip uninstall -y setuptools wheel pip && \
    rm -rf /usr/local/lib/python3.11/site-packages/pip \
           /usr/local/lib/python3.11/site-packages/pip-*.dist-info

# ---- runtime 阶段：仅拷贝构建产物，非 root 运行 ----
FROM python:3.11-slim

LABEL org.opencontainers.image.title="flower-web-infrastructure" \
      org.opencontainers.image.description="Web 系统通用后端基础设施（单体 / 微服务通用基础依赖）" \
      org.opencontainers.image.licenses="MIT"

# 时区与基础工具（TZ 数据避免日志时间偏移；curl 供健康检查兜底）
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 拷贝 build 阶段安装的全部第三方依赖 + web_infra 包（含随 package-data 安装的
# site-packages/web_infra/config/application.default.yml，pip 安装产物与运行时 site-packages 路径一致）
COPY --from=build /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
# 同时保留源码副本于 /app/src（供调试/挂载参考；运行时 import 解析走 site-packages）
COPY src ./src

# 非 root 运行（安全基线）；合并 RUN 减少层数
# 1) 系统包升级（2026-08-17 整改）：基础镜像 python:3.11-slim 浮动标签可能拉取到未含安全修复的
#    快照（如 util-linux 2.41-5 存在 CVE-2026-53615，修复版 2.41.5-0+deb13u1），
#    启动时统一 apt-get upgrade 到 Debian 仓库最新，保证最终镜像系统包无高危漏洞。
# 2) 清理基础镜像 python:3.11-slim 自带的构建期工具（pip/setuptools/wheel 及其 vendored 依赖）：
#    COPY --from=build 只叠加不删除，基础镜像自带的 setuptools-79.0.1（内置 wheel 0.45.1 / jaraco.context 5.3.0）
#    与 pip-24.0 若不清理会残留进最终镜像，导致 Trivy 高危漏洞（CVE-2026-24049 / CVE-2026-23949）阻断 CI。
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade --no-install-recommends -y \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/python3.11/site-packages/pip \
           /usr/local/lib/python3.11/site-packages/pip-*.dist-info \
           /usr/local/lib/python3.11/site-packages/setuptools \
           /usr/local/lib/python3.11/site-packages/setuptools-*.dist-info \
           /usr/local/lib/python3.11/site-packages/pkg_resources \
           /usr/local/lib/python3.11/site-packages/pkg_resources-*.dist-info \
           /usr/local/lib/python3.11/site-packages/_distutils_hack \
           /usr/local/lib/python3.11/site-packages/distutils-precedence.pth \
           /usr/local/lib/python3.11/site-packages/wheel \
           /usr/local/lib/python3.11/site-packages/wheel-*.dist-info \
    && useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENV APP_HOST=0.0.0.0 \
    APP_PORT=8000

# 默认以框架默认配置启动（含 /health/live /health/ready /health /metrics 端点）；业务项目 FROM 后挂载 application.yml 并覆盖 CMD
CMD ["python", "-c", "import os, uvicorn; from web_infra import create_app; uvicorn.run(create_app(), host=os.environ['APP_HOST'], port=int(os.environ['APP_PORT']), log_level='info')"]

# 健康检查（整改 S19-1）：容器存活用 /health/live（进程存活，不探测依赖，组件 DOWN 不摘除容器）；
# 就绪探测用 /health/ready（依赖连通性 + 启动完成），由编排层（K8s readinessProbe 等）使用
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).status == 200 else 1)"
