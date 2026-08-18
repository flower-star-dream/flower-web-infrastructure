"""
容量评估 HTTP 端点与 HTML 可视化

@Author: 花海
@Date: 2026/08/18 09:00
@Description: /capacity 端点（设计文档《并发访问能力评估设计.md》§7.1/§7.2）：
              内容协商返回 JSON（BigIntJSONResponse 对齐框架）或 HTML 可视化页面
              （复用 metrics_html 的 should_render_html 内容协商模式，不引前端库）。
              端点由 Application 装配时注册（app.capacity.enabled=true），可选注入
              DiagnosticAccessGuard（生产 IP 白名单，见 infra/web/diagnostic_access.py）；
              guard 未命中时返回 403 JSON。页面区块：理论容量（逐组件上限表格 + 瓶颈标注）、
              运行时状态（QPS/并发/CPU + 利用率）、限流/SLO 反推、集群视图、建议。
"""
from __future__ import annotations

from html import escape
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from web_infra.capabilities.capacity.assessor import CapacityAssessor
from web_infra.capabilities.capacity.report import CapacityReport
from web_infra.infra.constants import HttpStatusConstant
from web_infra.infra.error import CommonErrorCode
from web_infra.infra.monitoring.metrics_html import should_render_html
from web_infra.infra.web.json_response import BigIntJSONResponse

# 403 拒绝响应体（守卫未命中/生产无 IP；复用 CommonErrorCode.ACCESS_DENIED 正式错误码）
_ACCESS_DENIED_BODY = {
    "code": CommonErrorCode.ACCESS_DENIED.code,
    "message": CommonErrorCode.ACCESS_DENIED.message,
    "data": None,
}


def register_capacity_endpoints(
    app: FastAPI,
    assessor: CapacityAssessor,
    service_name: str = "web-infra",
    access_guard: Callable[[Request], bool] | None = None,
) -> None:
    """注册 /capacity 端点。

    :param app: FastAPI 应用实例
    :param assessor: 容量评估编排器（评估入口）
    :param service_name: 报告中的服务名标识（页眉展示）
    :param access_guard: 访问守卫 `(request) -> 是否放行`；None 不限制。
        生产环境由 Application 注入 DiagnosticAccessGuard（IP 白名单），
        未命中时端点返回 403（守卫拒绝优先于业务评估）。
    """

    @app.get("/capacity")
    async def capacity_endpoint(request: Request, format: str | None = None) -> Any:
        """容量评估端点：内容协商返回 JSON 或 HTML。

        浏览器（Accept 含 text/html）返回 HTML 页面，Prometheus/Grafana 或 API
        调用返回 JSON（可通过 ?format=text / ?format=html 强制指定格式）。
        """
        if access_guard is not None and not access_guard(request):
            return BigIntJSONResponse(
                status_code=HttpStatusConstant.HTTP_FORBIDDEN,
                content=_ACCESS_DENIED_BODY,
            )

        report = await assessor.assess(include_cluster=True)
        if should_render_html(format, request.headers.get("accept")):
            return HTMLResponse(render_capacity_html(report, service_name))
        return BigIntJSONResponse(status_code=HttpStatusConstant.HTTP_OK, content=report.as_dict())


def render_capacity_html(report: CapacityReport, service_name: str = "web-infra") -> str:
    """渲染容量评估 HTML 页面（§7.2 五区块，纯静态字符串拼接，无前端依赖）。"""
    rows = "".join(
        f"<tr><td>{escape(c.name)}</td><td>{c.concurrency_limit if c.concurrency_limit is not None else 'N/A'}"
        f"</td><td>{escape(c.description)}</td></tr>"
        for c in report.static.components
    )
    runtime = report.runtime
    runtime_rows = ""
    if runtime is not None:
        utilization = report.utilization_ratio
        runtime_rows = f"""
        <div class="card">
          <h3>运行时状态</h3>
          <p>当前 QPS：<b>{runtime.current_qps if runtime.current_qps is not None else 'N/A'}</b>
             | 当前并发：<b>{runtime.current_concurrency if runtime.current_concurrency is not None else 'N/A'}</b>
             | 当前 CPU：<b>{runtime.current_cpu_percent if runtime.current_cpu_percent is not None else 'N/A'}%</b>
             | 窗口样本数：<b>{runtime.sample_count}</b></p>
          <p>QPS 峰值：<b>{runtime.qps_peak if runtime.qps_peak is not None else 'N/A'}</b>
             | 错误率：<b>{runtime.error_ratio if runtime.error_ratio is not None else 'N/A'}</b>
             | P95 延迟：<b>{runtime.latency_p95 if runtime.latency_p95 is not None else 'N/A'}s</b></p>
          <p>利用率：<b>{utilization if utilization is not None else 'N/A'}</b>（当前 QPS ÷ 理论 QPS）</p>
        </div>"""
    else:
        runtime_rows = '<div class="card"><h3>运行时状态</h3><p>未运行（CLI 仅静态估算）</p></div>'

    cluster_rows = ""
    if report.cluster is not None and report.cluster.instance_count > 0:
        cluster_rows = "".join(
            f"<tr><td>{escape(i.url)}</td><td>{escape(i.status)}</td>"
            f"<td>{i.qps if i.qps is not None else 'N/A'}</td><td>{escape(i.error or '')}</td></tr>"
            for i in report.cluster.instances
        )
        cluster_rows = f"""
        <div class="card">
          <h3>集群视图</h3>
          <p>实例数：<b>{report.cluster.instance_count}</b> | 不可达：<b>{report.cluster.unreachable_count}</b>
             | 集群总 QPS：<b>{report.cluster.total_qps if report.cluster.total_qps is not None else 'N/A'}</b></p>
          <table><tr><th>实例</th><th>状态</th><th>QPS</th><th>错误</th></tr>{cluster_rows}</table>
        </div>"""

    suggestions = "".join(f"<li>{escape(s)}</li>" for s in report.suggestions)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{escape(service_name)} - 并发访问能力评估</title>
<style>
body {{ font-family: -apple-system, Segoe UI, sans-serif; margin: 24px; color: #222; background: #f7f7f7; }}
h1 {{ font-size: 20px; }} h2 {{ font-size: 16px; margin-top: 24px; }}
.card {{ background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 12px 16px; margin: 12px 0; }}
table {{ border-collapse: collapse; width: 100%; }} th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 13px; }}
th {{ background: #f0f0f0; }} li {{ font-size: 13px; margin: 4px 0; }}
.muted {{ color: #888; font-size: 12px; }}
</style></head><body>
<h1>{escape(service_name)} · 并发访问能力评估</h1>
<p class="muted">生成时间：{escape(report.generated_at)}</p>
<div class="card">
  <h2>理论容量</h2>
  <p>整体并发上限：<b>{report.static.concurrency_limit if report.static.concurrency_limit is not None else 'N/A'}</b>
     | 理论 QPS：<b>{report.static.theoretical_max_qps if report.static.theoretical_max_qps is not None else 'N/A'}</b>
     | 安全水位 QPS：<b>{report.static.safe_qps if report.static.safe_qps is not None else 'N/A'}</b>
     | 瓶颈：<b>{escape(report.static.bottleneck or 'N/A')}</b>
     | CPU 核数：<b>{report.static.cpu_cores if report.static.cpu_cores is not None else 'N/A'}</b></p>
  <table><tr><th>维度</th><th>并发上限</th><th>口径</th></tr>{rows}</table>
</div>
<div class="card">
  <h3>限流 / SLO 反推</h3>
  <p>限流 QPS：<b>{report.static.rate_limit_qps if report.static.rate_limit_qps is not None else '未启用'}</b>
     | 生效最大 QPS：<b>{report.static.effective_max_qps if report.static.effective_max_qps is not None else 'N/A'}</b>
     | 允许错误率：<b>{report.static.allowed_error_ratio}</b></p>
</div>
{runtime_rows}
{cluster_rows}
<div class="card"><h3>建议</h3><ul>{suggestions}</ul></div>
</body></html>"""
