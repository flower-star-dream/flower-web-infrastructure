# =====================================================================
# flower-web-infrastructure 基础镜像（整改 S20-2：多阶段构建）
# @Author: 花海
# @Date: 2026/08/14 22:00
# @Description: 基础设施库基础镜像：安装 web_infra 依赖并默认启动 create_app()（含 /health/live /health/ready /health /metrics），
#               业务项目通过 FROM 继承本镜像（挂载 application.yml 与业务代码后覆盖启动命令）。
#               构建分两阶段：build 阶段完成 pip 依赖安装；runtime 阶段仅拷贝 site-packages + 源码，产物更小更安全。
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
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && \
    pip install .

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
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
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
