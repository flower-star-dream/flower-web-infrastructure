"""/metrics 端点 HTML 格式化渲染模块

浏览器访问 /metrics 时返回格式化 HTML 页面（按业务分组展示指标），
Prometheus 抓取时仍返回 OpenMetrics 原始文本（内容协商，不破坏监控采集）。

主要能力：
- 顶部概览统计卡（总请求 / 当前并发 / 错误数 / 平均耗时 / 慢请求 / 慢 SQL / AI 调用）；
- HTTP RED 指标按 service（模块/服务）分类，模块与接口均可折叠；
- 按业务分组导航展示指标（HTTP RED / 阶段耗时 / 慢请求与慢 SQL / 连接池 / 缓存 / 消息队列 /
  对象存储 / 注册中心 / 线程池 / Python 运行时 / AI 模型指标 / SPI 自定义分组）；
- 分组按实际样本动态渲染：未启用组件（懒注册未触发）或未埋点指标的分组不展现，
  由组件启用配置决定指标是否采集与展示；
- 直方图指标展示 _count/_sum 与估算分位数（P50/P95/P99），bucket 明细可折叠；
- 支持一键展开/折叠全部、亮/暗主题切换（localStorage 记忆）；
- SPI 扩展：业务通过 MetricGroupProviderRegistry 注册自定义指标分组后，页面自动归组展示；
- ?format=text 强制原始文本、?format=html 强制 HTML。

@Author: 花海
@Date: 2026/08/14 22:00
@Description: Prometheus 指标 HTML 格式化页面：模块化折叠、接口明细、分位数估算与 SPI 自定义分组
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from prometheus_client import REGISTRY

from web_infra.infra.monitoring.metric_group_provider_registry import MetricGroupProviderRegistry
from web_infra.infra.monitoring.metrics import _service, get_slow_sql_samples


def should_render_html(fmt: str | None, accept: str | None) -> bool:
    """内容协商：判断请求是否应返回 HTML 页面。

    优先级：
    1. ?format=text  强制返回 Prometheus 原始文本；
    2. ?format=html  强制渲染 HTML 页面；
    3. 否则按 Accept 头判断（浏览器请求偏好 text/html 时渲染 HTML）。

    :param fmt: 查询参数 format 的值（可为 None）
    :param accept: 请求 Accept 头（可为 None）
    :return: 是否渲染 HTML 页面
    """
    if fmt == "text":
        return False
    if fmt == "html":
        return True
    return "text/html" in (accept or "")


def histogram_quantile(buckets: list[tuple[float, float]], quantile: float) -> float | None:
    """按 Prometheus histogram_quantile 算法估算分位数。

    :param buckets: 上边界与累计计数对列表，必须按上边界升序（含 +Inf 桶）
    :param quantile: 分位数，0~1（如 0.95）
    :return: 估算的分位数值；样本为空或参数非法时返回 None
    """
    if not buckets or not 0 <= quantile <= 1:
        return None
    total = buckets[-1][1]
    if total <= 0:
        return None
    rank = quantile * total
    for i, (upper, cumulative) in enumerate(buckets):
        if cumulative >= rank:
            if i == 0:
                return upper
            lower = buckets[i - 1][0]
            count_in_bucket = cumulative - buckets[i - 1][1]
            if count_in_bucket > 0:
                return lower + (upper - lower) * (rank - buckets[i - 1][1]) / count_in_bucket
            return upper
    return buckets[-1][0]


# 指标分组定义：(分组名, 指标名前缀集合)；命中即归入该组，未命中归入"其他"。
# 内置分组仅覆盖本框架已定义的指标；业务自定义指标通过 SPI 注册表（MetricGroupProviderRegistry）扩展。
# 未启用组件（缓存/存储/消息队列/注册中心等）的指标为懒注册，无样本，页面按样本过滤后不展现该分组。
_METRIC_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("HTTP RED 指标", ("http_requests_total", "http_request_errors_total", "http_request_duration_seconds", "http_requests_in_flight")),
    ("全链路分阶段耗时", ("request_phase_duration_seconds",)),
    ("慢请求 / 慢 SQL", ("slow_request_total", "slow_sql_total")),
    ("MySQL 连接池", ("mysql_pool_",)),
    ("Redis / MongoDB 连接池", ("redis_pool_", "mongo_pool_")),
    ("缓存指标", ("cache_",)),
    ("消息队列指标", ("mq_",)),
    ("对象存储指标", ("storage_",)),
    ("注册中心指标", ("registry_",)),
    ("线程池", ("thread_pool_",)),
    ("Python 运行时", ("python_",)),
    ("AI 模型指标", ("ai_llm_", "ai_token_", "ai_cost_")),
]

# AI 调用指标 outcome 标签 -> 中文说明
_AI_OUTCOME_ZH: dict[str, str] = {
    "success": "成功",
    "error": "失败",
    "degraded": "降级",
    "cache_hit": "缓存命中",
    "cache_miss": "缓存未命中",
}


def _metric_display_name(metric) -> str:
    """推导指标的完整展示名。

    prometheus-client 0.26 的 metric.name 会剥离 Counter 的 _total 后缀
    （如 http_requests_total -> http_requests），分组与展示需还原完整名称。
    通过样本名去掉 _bucket/_sum/_count/_created 后缀得到基础名。

    :param metric: prometheus_client 收集的指标对象
    :return: 完整指标名，如 http_requests_total
    """
    names = [s.name for s in metric.samples]
    if not names:
        # 无样本时无法从样本名还原；Counter 的 _total 后缀已被剥离，需补回
        base = metric.name
        if metric.type == "counter" and not base.endswith("_total"):
            base += "_total"
        return base
    base = names[0]
    for suffix in ("_bucket", "_sum", "_count", "_created"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base


def _metric_group(metric_name: str) -> str:
    """按指标名前缀返回所属分组名；内置分组优先，其次 SPI 自定义分组，未命中返回"其他"。"""
    for group_name, prefixes in _METRIC_GROUPS:
        if any(metric_name == prefix or metric_name.startswith(prefix) for prefix in prefixes):
            return group_name
    return MetricGroupProviderRegistry.group_of(metric_name) or "其他"


def _is_duration_metric(metric_name: str) -> bool:
    """耗时类指标（直方图单位为秒）在页面中转为毫秒展示，更直观。"""
    return "duration" in metric_name or metric_name.endswith("_seconds")


def _fmt_value(value: float, as_duration: bool) -> str:
    """格式化指标数值。

    :param value: 原始数值
    :param as_duration: 是否按耗时展示（**统一以毫秒展示**，含千分位，
        避免秒/毫秒混用导致单位不一致）
    :return: 展示字符串
    """
    if value != value:  # NaN
        return "-"
    if as_duration:
        return f"{value * 1000:,.1f} ms"
    if value == int(value):
        return str(int(value))
    return f"{value:.6g}"


def _series_label_text(display_name: str, labels: tuple[tuple[str, str], ...]) -> str:
    """生成直方图 series 的标签展示文本。

    内置映射：AI 调用指标（ai_llm_calls_total）的 outcome 标签译为中文；
    SPI 自定义分组：优先使用提供者声明的 series_label_zh 中文说明；
    其余指标保持 k=v 格式。

    :param display_name: 指标完整展示名
    :param labels: (标签名, 标签值) 元组列表
    :return: 标签展示文本
    """
    if display_name == "ai_llm_calls_total":
        parts = []
        for k, v in labels:
            if k == "outcome":
                zh = _AI_OUTCOME_ZH.get(v)
                parts.append(f"{k}={zh}（{v}）" if zh and zh != v else f"{k}={v}")
            else:
                parts.append(f"{k}={v}")
        return ", ".join(parts)
    group_name = MetricGroupProviderRegistry.group_of(display_name)
    if group_name:
        provider = MetricGroupProviderRegistry.provider_of(group_name)
        if provider is not None:
            zh = provider.series_label_zh(display_name, labels)
            if zh:
                return zh
    return ", ".join(f"{k}={v}" for k, v in labels) or "无标签"


def _render_table(rows: list[list[str]]) -> str:
    """渲染指标值表格 HTML。

    :param rows: 表头（第一行）+ 数据行
    :return: 表格 HTML 字符串
    """
    header = "".join(f"<th>{escape(str(c))}</th>" for c in rows[0])
    body = ""
    for row in rows[1:]:
        cells = "".join(f"<td>{escape(str(c))}</td>" for c in row)
        body += f"<tr>{cells}</tr>"
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _render_histogram(metric) -> str:
    """渲染直方图指标：按 label 组合分组，展示 count/sum 与分位数，bucket 明细折叠。

    :param metric: prometheus_client 收集的指标对象
    :return: 区块 HTML 字符串
    """
    # 按非 le 标签组合聚合 bucket/count/sum 样本
    series: dict[tuple, dict[str, Any]] = {}
    for sample in metric.samples:
        labels = tuple(sorted((k, v) for k, v in sample.labels.items() if k != "le"))
        entry = series.setdefault(labels, {"buckets": [], "count": 0.0, "sum": 0.0})
        if sample.name.endswith("_bucket"):
            entry["buckets"].append((float(sample.labels.get("le", "+Inf") or float("inf")), sample.value))
        elif sample.name.endswith("_count"):
            entry["count"] = sample.value
        elif sample.name.endswith("_sum"):
            entry["sum"] = sample.value

    if not series:
        return "<p class='empty'>暂无数据</p>"

    display_name = _metric_display_name(metric)
    html = ""
    for labels, entry in series.items():
        label_text = _series_label_text(display_name, labels)
        buckets = sorted(entry["buckets"])
        p50 = histogram_quantile(buckets, 0.50)
        p95 = histogram_quantile(buckets, 0.95)
        p99 = histogram_quantile(buckets, 0.99)
        as_duration = _is_duration_metric(display_name)
        quantile_rows = [
            ["分位", "P50", "P95", "P99"],
            [
                "-",
                _fmt_value(p50, as_duration) if p50 is not None else "-",
                _fmt_value(p95, as_duration) if p95 is not None else "-",
                _fmt_value(p99, as_duration) if p99 is not None else "-",
            ],
            ["样本数", str(int(entry["count"])), "", ""],
            ["累计值", _fmt_value(entry["sum"], as_duration), "", ""],
        ]
        bucket_rows = [["上边界", "累计计数"], *[[_fmt_value(upper, as_duration), str(int(cum))] for upper, cum in buckets]]
        html += (
            f"<div class='series'><div class='series-label'>{escape(label_text)}</div>"
            f"{_render_table(quantile_rows)}"
            f"<details><summary>查看 {len(buckets)} 个分桶</summary>{_render_table(bucket_rows)}</details>"
            f"</div>"
        )
    return html


def _render_metric(metric) -> str:
    """按指标类型渲染单个指标区块。

    :param metric: prometheus_client 收集的指标对象
    :return: 区块 HTML 字符串
    """
    display_name = _metric_display_name(metric)
    if metric.type == "histogram":
        body = _render_histogram(metric)
    else:
        as_duration = _is_duration_metric(display_name)
        header_row = ["标签组合", "值"]
        rows = [header_row]
        for sample in metric.samples:
            # 过滤 prometheus-client 自动生成的 _created 时间戳样本（OpenMetrics 约定）
            if sample.name.endswith("_created"):
                continue
            labels = tuple(sorted(sample.labels.items()))
            rows.append([_series_label_text(display_name, labels), _fmt_value(sample.value, as_duration)])
        body = _render_table(rows) if len(rows) > 1 else "<p class='empty'>暂无数据</p>"
    return (
        f"<section class='metric'><h3><code>{escape(display_name)}</code> "
        f"<span class='type'>{escape(str(metric.type))}</span></h3>"
        f"<p class='help'>{escape(metric.documentation or '')}</p>{body}</section>"
    )


def _render_slow_sql_detail() -> str:
    """渲染「最近慢 SQL」明细区块（§18.5.3 页面展示）。

    展示环形缓存中的最近慢 SQL 记录（时间/数据源/级别/耗时/SQL 语句），
    缓存为空时展示「暂无慢 SQL 记录」。

    :return: 区块 HTML 字符串
    """
    samples = get_slow_sql_samples()
    if not samples:
        return (
            "<section class='metric'><h3><code>最近慢 SQL</code> "
            "<span class='type'>明细</span></h3>"
            "<p class='help'>慢 SQL 阈值：200ms（P2）/ 2s（P1）；slow_sql_total 按 severity 分级计数（warning/critical），仅展示最近 20 条</p>"
            "<p class='empty'>暂无慢 SQL 记录</p></section>"
        )
    rows = [["时间", "数据源", "级别", "耗时", "SQL 语句"]]
    for s in samples:
        rows.append([
            s["time"],
            s["datasource"],
            s["alert_level"],
            _fmt_value(s["duration_ms"] / 1000.0, True),
            s["sql"],
        ])
    return (
        f"<section class='metric'><h3><code>最近慢 SQL</code> "
        f"<span class='type'>明细</span></h3>"
        f"<p class='help'>最近 {len(samples)} 条慢 SQL（阈值：200ms P2 / 2s P1；slow_sql_total 按 severity 分级计数）</p>"
        f"<div class='slow-sql-wrap'>{_render_table(rows)}</div></section>"
    )


def _collect_http_red(metrics: list[tuple[str, Any]]) -> dict[str, dict[str, Any]]:
    """聚合 HTTP RED 指标为「service -> path -> method」的嵌套结构。

    从 http_requests_total / http_request_errors_total / http_request_duration_seconds /
    http_requests_in_flight 四类指标样本中提取数据，用于按模块/服务分类折叠展示各接口。

    :param metrics: 与 HTTP RED 组匹配的 (指标名, 指标对象) 列表
    :return: 形如 {"user": {"paths": {path: {"methods": {method: {...}}}}, "total": ...}} 的结构
    """

    def _svc(name: str) -> dict[str, Any]:
        return services.setdefault(name, {"paths": {}, "total": 0.0, "errors": 0.0, "sum": 0.0, "count": 0.0, "inflight": 0.0})

    def _path(svc: dict[str, Any], path: str) -> dict[str, Any]:
        return svc["paths"].setdefault(path, {"methods": {}, "total": 0.0, "errors": 0.0, "sum": 0.0, "count": 0.0})

    def _method(p: dict[str, Any], method: str) -> dict[str, Any]:
        return p["methods"].setdefault(method, {"total": 0.0, "errors": 0.0, "sum": 0.0, "count": 0.0, "buckets": []})

    services: dict[str, dict[str, Any]] = {}
    for display_name, metric in metrics:
        if display_name == "http_requests_total":
            for sample in metric.samples:
                if sample.name.endswith("_created"):
                    continue
                svc = _svc(sample.labels.get("service", "unknown"))
                p = _path(svc, sample.labels.get("path", ""))
                p["methods"].setdefault(
                    sample.labels.get("method", ""),
                    {"total": 0.0, "errors": 0.0, "sum": 0.0, "count": 0.0, "buckets": []},
                )["total"] += sample.value
                p["total"] += sample.value
                svc["total"] += sample.value
        elif display_name == "http_request_errors_total":
            for sample in metric.samples:
                if sample.name.endswith("_created"):
                    continue
                svc = _svc(sample.labels.get("service", "unknown"))
                p = _path(svc, sample.labels.get("path", ""))
                p["methods"].setdefault(
                    sample.labels.get("method", ""),
                    {"total": 0.0, "errors": 0.0, "sum": 0.0, "count": 0.0, "buckets": []},
                )["errors"] += sample.value
                p["errors"] += sample.value
                svc["errors"] += sample.value
        elif display_name == "http_request_duration_seconds":
            for sample in metric.samples:
                svc = _svc(sample.labels.get("service", "unknown"))
                p = _path(svc, sample.labels.get("path", ""))
                m = p["methods"].setdefault(
                    sample.labels.get("method", ""),
                    {"total": 0.0, "errors": 0.0, "sum": 0.0, "count": 0.0, "buckets": []},
                )
                if sample.name.endswith("_bucket"):
                    m["buckets"].append((float(sample.labels.get("le", "+Inf") or float("inf")), sample.value))
                elif sample.name.endswith("_sum"):
                    m["sum"] = sample.value
                    p["sum"] += sample.value
                    svc["sum"] += sample.value
                elif sample.name.endswith("_count"):
                    m["count"] = sample.value
                    p["count"] += sample.value
                    svc["count"] += sample.value
        elif display_name == "http_requests_in_flight":
            for sample in metric.samples:
                if sample.name.endswith("_created"):
                    continue
                _svc(sample.labels.get("service", "unknown"))["inflight"] += sample.value
    return services


def _render_http_red_group(metrics: list[tuple[str, Any]]) -> str:
    """渲染 HTTP RED 指标组：按 service（模块/服务）分类，模块与接口均可折叠。

    聚合后每个 service 为一个可折叠区块（默认展开），块内每个接口（path）为
    独立可折叠项（默认收起），展开后展示该接口各方法的请求数/错误数/平均耗时/P50/P95/P99。

    :param metrics: 与 HTTP RED 组匹配的 (指标名, 指标对象) 列表
    :return: HTML 字符串
    """
    services = _collect_http_red(metrics)
    if not services:
        return (
            "<section class='metric'><h3><code>http_requests_total</code> "
            "<span class='type'>counter</span></h3>"
            "<p class='empty'>暂无请求数据</p></section>"
        )

    blocks = ""
    for svc_name, svc in sorted(services.items(), key=lambda item: -item[1]["total"]):
        # 模块概要统计（请求数 / 错误数 / 当前并发 / 平均耗时）
        avg = svc["sum"] / svc["count"] if svc["count"] > 0 else None
        svc_meta = f"请求 <b>{int(svc['total']):,}</b> · 错误 <b>{int(svc['errors']):,}</b>"
        if svc["inflight"]:
            svc_meta += f" · 并发 <b>{int(svc['inflight'])}</b>"
        if avg is not None:
            svc_meta += f" · 平均 {_fmt_value(avg, True)}"

        paths_html = ""
        for path, p in sorted(svc["paths"].items(), key=lambda item: -item[1]["total"]):
            path_avg = p["sum"] / p["count"] if p["count"] > 0 else None
            # 接口概要统计
            path_meta = f"请求 <b>{int(p['total']):,}</b> · 错误 <b>{int(p['errors']):,}</b>"
            if path_avg is not None:
                path_meta += f" · 平均 {_fmt_value(path_avg, True)}"
            # 接口明细表（按方法拆分）
            rows = [["方法", "请求数", "错误数", "平均耗时", "P50", "P95", "P99"]]
            for method, m in sorted(p["methods"].items()):
                buckets = sorted(m["buckets"])
                p50 = histogram_quantile(buckets, 0.50)
                p95 = histogram_quantile(buckets, 0.95)
                p99 = histogram_quantile(buckets, 0.99)
                m_avg = m["sum"] / m["count"] if m["count"] > 0 else None
                rows.append([
                    method or "-",
                    str(int(m["total"])),
                    str(int(m["errors"])),
                    _fmt_value(m_avg, True) if m_avg is not None else "-",
                    _fmt_value(p50, True) if p50 is not None else "-",
                    _fmt_value(p95, True) if p95 is not None else "-",
                    _fmt_value(p99, True) if p99 is not None else "-",
                ])
            paths_html += (
                f"<details class='path'><summary>"
                f"<code class='path-method'>{escape(path or '-')}</code>"
                f"<span class='path-meta'>{path_meta}</span></summary>"
                f"{_render_table(rows)}</details>"
            )

        blocks += (
            f"<details class='svc' open><summary>"
            f"<span class='svc-badge'>{escape(svc_name)}</span>"
            f"<span class='svc-meta'>{svc_meta}</span></summary>"
            f"<div class='svc-paths'>{paths_html}</div></details>"
        )

    return (
        f"<section class='metric'><h3><code>http_requests_total</code> "
        f"<span class='type'>counter</span></h3>"
        f"<p class='help'>HTTP 请求总数（RED Rate，按模块/服务分类，接口可折叠）</p>"
        f"<div class='http-red'>{blocks}</div></section>"
    )


def _render_overview_cards(flat_metrics: list[tuple[str, Any]]) -> str:
    """渲染顶部概览统计卡（总请求 / 并发 / 错误 / 平均耗时 / 慢请求 / 慢 SQL / AI 调用）。

    :param flat_metrics: 全部 (指标名, 指标对象) 列表
    :return: 概览卡 HTML 字符串
    """
    values = {
        "requests": 0.0,
        "inflight": 0.0,
        "errors": 0.0,
        "slow_req": 0.0,
        "slow_sql": 0.0,
        "ai_calls": 0.0,
    }
    http_sum = 0.0
    http_count = 0.0
    for display_name, metric in flat_metrics:
        if display_name == "http_requests_total":
            values["requests"] += sum(s.value for s in metric.samples if not s.name.endswith("_created"))
        elif display_name == "http_requests_in_flight":
            values["inflight"] += sum(s.value for s in metric.samples if not s.name.endswith("_created"))
        elif display_name == "http_request_errors_total":
            values["errors"] += sum(s.value for s in metric.samples if not s.name.endswith("_created"))
        elif display_name == "slow_request_total":
            values["slow_req"] += sum(s.value for s in metric.samples if not s.name.endswith("_created"))
        elif display_name == "slow_sql_total":
            values["slow_sql"] += sum(s.value for s in metric.samples if not s.name.endswith("_created"))
        elif display_name == "ai_llm_calls_total":
            values["ai_calls"] += sum(s.value for s in metric.samples if not s.name.endswith("_created"))
        elif display_name == "http_request_duration_seconds":
            for s in metric.samples:
                if s.name.endswith("_sum"):
                    http_sum += s.value
                elif s.name.endswith("_count"):
                    http_count += s.value

    avg = http_sum / http_count if http_count > 0 else None
    cards = [
        ("总请求", f"{int(values['requests']):,}", "req"),
        ("当前并发", str(int(values["inflight"])), "inflight"),
        ("错误数", f"{int(values['errors']):,}", "err"),
        ("平均耗时", _fmt_value(avg, True) if avg is not None else "-", "avg"),
        ("慢请求", f"{int(values['slow_req']):,}", "slow"),
        ("慢 SQL", f"{int(values['slow_sql']):,}", "sql"),
        ("AI 调用", f"{int(values['ai_calls']):,}", "ai"),
    ]
    return "".join(
        f"<div class='card' data-kind='{kind}'><div class='card-value'>{escape(value)}</div>"
        f"<div class='card-label'>{escape(label)}</div></div>"
        for label, value, kind in cards
    )


def _default_theme() -> str:
    """按当前系统时间返回默认主题（白天浅色、夜晚深色）。

    以 6:00-18:00 为日间窗口，其余时段为夜间。

    :return: "light" 或 "dark"
    """
    hour = datetime.now().hour
    return "light" if 6 <= hour < 18 else "dark"


def _normalize_theme(theme: str | None) -> str:
    """规范化主题参数；非法值回退为按时间计算的默认主题。

    :param theme: 主题参数值（light/dark/None）
    :return: "light" 或 "dark"
    """
    if theme in ("light", "dark"):
        return theme
    return _default_theme()


def _group_has_data(metrics: list) -> bool:
    """分组是否有实际样本数据（任一指标含非空样本）。

    未启用组件（懒注册未触发）或从未埋点（静态注册但无样本）的指标不视为有数据，
    其分组不渲染——由组件启用配置动态决定指标是否展现。
    """
    return any(metric.samples for _, metric in metrics)


def render_metrics_html(service_name: str | None = None, theme: str | None = None) -> str:
    """渲染 /metrics 的格式化 HTML 页面。

    顶部展示概览统计卡；指标按业务分组展示（内置分组 + SPI 自定义分组），
    HTTP RED 指标组内按 service（模块/服务）分类，模块与接口均可折叠；
    直方图展示分位数（P50/P95/P99）与可折叠的 bucket 明细。
    页面支持亮/暗主题与一键展开/折叠全部。

    :param service_name: 服务名；默认取 metrics 模块注入的服务名
    :param theme: 主题（light/dark）；缺省或非法时按系统时间决定
    :return: 完整 HTML 页面字符串
    """
    service = service_name or _service() or "unknown"
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    active_theme = _normalize_theme(theme)

    # 收集全部指标并按分组聚合（group -> [(metric_name, metric), ...]）
    groups: dict[str, list] = {}
    for metric in REGISTRY.collect():
        display_name = _metric_display_name(metric)
        groups.setdefault(_metric_group(display_name), []).append((display_name, metric))

    # 分组渲染顺序：内置定义分组 -> SPI 注册分组 -> 动态出现的"其他"；
    # 仅渲染有实际样本的分组（未启用/未埋点组件不展现，配置动态决定）。
    spi_groups = [p.group_name for p in MetricGroupProviderRegistry.all()]
    defined_groups = [name for name, _ in _METRIC_GROUPS] + [
        name for name in spi_groups if name not in [g for g, _ in _METRIC_GROUPS]
    ]
    group_names = [name for name in defined_groups if _group_has_data(groups.get(name, []))] + [
        name for name in groups if name not in defined_groups and _group_has_data(groups[name])
    ]

    flat_metrics = [item for items in groups.values() for item in items]
    nav_items = "".join(f"<a href='#g{group_id}'>{escape(group)}</a>" for group_id, group in enumerate(group_names))
    sections = ""
    for group_id, group in enumerate(group_names):
        group_metrics = sorted(groups.get(group, []))
        if not group_metrics:
            metrics_html = "<p class='empty'>暂无数据</p>"
        elif group == "HTTP RED 指标":
            metrics_html = _render_http_red_group(group_metrics)
        else:
            metrics_html = "".join(_render_metric(metric) for _, metric in group_metrics)
        # 慢请求 / 慢 SQL 分组追加「最近慢 SQL」明细区块（展示具体 SQL 语句）
        if group == "慢请求 / 慢 SQL" and group_metrics:
            metrics_html += _render_slow_sql_detail()
        sections += (
            f"<details class='group' id='g{group_id}' open>"
            f"<summary><h2>{escape(group)}</h2><span class='group-count'>{len(group_metrics)} 个指标</span></summary>"
            f"<div class='content-wrap'>{metrics_html}</div></details>"
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="{active_theme}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>指标总览 - {escape(service)}</title>
<style>
  /* 暗色主题（默认，夜晚） */
  [data-theme="dark"] {{ --bg:#0c1220; --bg-grad-1:#0f1830; --bg-grad-2:#141c2e; --panel:#182233; --panel-2:#1e2a40; --border:#2c3a55; --text:#d7e0ef; --muted:#8aa0c0; --accent:#4da3ff; --accent-2:#7c5cff; --code:#9ecbff; --th-bg:#1d2b44; --btn-bg:#1a2740; --ok:#3ecf8e; --warn:#ffb454; --err:#ff6b6b; }}
  /* 亮色主题（白天） */
  [data-theme="light"] {{ --bg:#eef1f7; --bg-grad-1:#e8edf8; --bg-grad-2:#f4f6fa; --panel:#ffffff; --panel-2:#f6f8fc; --border:#dde3ec; --text:#243044; --muted:#5f6f88; --accent:#1a73e8; --accent-2:#6c4dff; --code:#0b57d0; --th-bg:#eef2f8; --btn-bg:#ffffff; --ok:#1f9d61; --warn:#c47b0f; --err:#d94848; }}
  * {{ box-sizing:border-box; }}
  html {{ scroll-behavior:smooth; }}
  body {{ margin:0; padding:0 24px 40px; background:linear-gradient(180deg,var(--bg-grad-1) 0,var(--bg-grad-2) 320px) fixed,var(--bg); color:var(--text); font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",monospace; transition:background .3s,color .3s; }}
  header {{ max-width:1200px; margin:0 auto 18px; padding:26px 0 8px; }}
  h1 {{ margin:0 0 4px; font-size:22px; letter-spacing:.3px; }}
  h1::before {{ content:"📊 "; }}
  .meta {{ color:var(--muted); font-size:12px; }}
  .meta a {{ color:var(--accent); text-decoration:none; }}
  .meta a:hover {{ text-decoration:underline; }}
  .toolbar {{ margin-top:12px; display:flex; gap:8px; flex-wrap:wrap; }}
  .btn {{ cursor:pointer; border:1px solid var(--border); background:var(--btn-bg); color:var(--accent); border-radius:16px; padding:5px 14px; font-size:12px; font-family:inherit; transition:all .2s; }}
  .btn:hover {{ border-color:var(--accent); box-shadow:0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent); }}
  .cards {{ max-width:1200px; margin:0 auto 22px; display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }}
  .card {{ background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:14px 16px; position:relative; overflow:hidden; transition:transform .15s,box-shadow .2s; }}
  .card:hover {{ transform:translateY(-2px); box-shadow:0 8px 20px rgba(0,0,0,.12); }}
  .card::before {{ content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--accent); }}
  .card[data-kind="err"]::before {{ background:var(--err); }}
  .card[data-kind="slow"]::before, .card[data-kind="sql"]::before {{ background:var(--warn); }}
  .card[data-kind="ai"]::before {{ background:var(--accent-2); }}
  .card-value {{ font-size:22px; font-weight:700; line-height:1.2; color:var(--text); }}
  .card-label {{ margin-top:4px; font-size:12px; color:var(--muted); }}
  nav {{ max-width:1200px; margin:0 auto 20px; display:flex; flex-wrap:wrap; gap:8px; }}
  nav a {{ color:var(--accent); text-decoration:none; border:1px solid var(--border); background:var(--panel); padding:5px 14px; border-radius:16px; font-size:12px; transition:all .2s; }}
  nav a:hover {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  details.group {{ max-width:1200px; margin:0 auto 18px; background:var(--panel); border:1px solid var(--border); border-radius:12px; overflow:hidden; scroll-margin-top:16px; }}
  details.group > summary {{ display:flex; align-items:center; gap:10px; padding:14px 20px; cursor:pointer; list-style:none; user-select:none; transition:background .15s; }}
  details.group > summary::-webkit-details-marker {{ display:none; }}
  details.group > summary::before {{ content:"▾"; color:var(--accent); font-size:13px; transition:transform .2s; }}
  details.group:not([open]) > summary::before {{ transform:rotate(-90deg); }}
  details.group > summary:hover {{ background:var(--panel-2); }}
  details.group > summary h2 {{ margin:0; font-size:15px; flex:1; }}
  .group-count {{ color:var(--muted); font-size:11px; border:1px solid var(--border); border-radius:10px; padding:1px 8px; }}
  details.group > .content-wrap {{ padding:4px 20px 18px; }}
  .metric {{ margin:0 0 16px; padding-top:14px; }}
  .metric h3 {{ margin:0 0 4px; font-size:14px; display:flex; align-items:center; gap:8px; }}
  .metric h3 code {{ color:var(--code); background:var(--panel-2); border:1px solid var(--border); border-radius:6px; padding:1px 8px; font-size:12px; }}
  .type {{ color:var(--muted); font-size:11px; border:1px solid var(--border); border-radius:10px; padding:1px 8px; }}
  .help {{ margin:2px 0 10px; color:var(--muted); font-size:12px; }}
  .empty {{ color:var(--muted); font-size:13px; padding:14px 0; }}
  table {{ border-collapse:collapse; width:100%; margin:8px 0; }}
  th, td {{ border:1px solid var(--border); padding:6px 12px; text-align:left; font-size:12px; }}
  th {{ background:var(--th-bg); color:var(--muted); font-weight:600; }}
  tbody tr:hover {{ background:var(--panel-2); }}
  td:not(:first-child) {{ text-align:right; font-variant-numeric:tabular-nums; }}
  details {{ margin-top:6px; }}
  summary {{ cursor:pointer; color:var(--accent); font-size:12px; }}
  .series {{ margin:8px 0; padding:10px 12px; background:var(--panel-2); border:1px solid var(--border); border-radius:8px; }}
  .series-label {{ color:var(--code); margin-bottom:6px; font-size:12px; }}
  /* HTTP RED 模块折叠区 */
  .http-red {{ display:flex; flex-direction:column; gap:10px; }}
  details.svc {{ background:var(--panel-2); border:1px solid var(--border); border-radius:10px; overflow:hidden; }}
  details.svc > summary {{ display:flex; align-items:center; gap:12px; padding:10px 14px; cursor:pointer; list-style:none; user-select:none; }}
  details.svc > summary::-webkit-details-marker {{ display:none; }}
  details.svc > summary::before {{ content:"▾"; color:var(--accent); font-size:12px; transition:transform .2s; }}
  details.svc:not([open]) > summary::before {{ transform:rotate(-90deg); }}
  details.svc > summary:hover {{ background:var(--panel); }}
  .svc-badge {{ background:var(--accent); color:#fff; font-size:11px; font-weight:600; border-radius:10px; padding:2px 12px; letter-spacing:.5px; }}
  .svc-meta {{ color:var(--muted); font-size:12px; }}
  .svc-meta b {{ color:var(--text); }}
  .svc-paths {{ display:flex; flex-direction:column; gap:8px; padding:0 0 12px; }}
  details.path {{ background:var(--panel); border:1px solid var(--border); border-radius:8px; overflow:hidden; }}
  details.path > summary {{ display:flex; align-items:center; gap:10px; padding:8px 12px; cursor:pointer; list-style:none; user-select:none; font-size:12px; }}
  details.path > summary::-webkit-details-marker {{ display:none; }}
  details.path > summary::before {{ content:"▸"; color:var(--muted); font-size:11px; transition:transform .2s; }}
  details.path[open] > summary::before {{ content:"▾"; }}
  details.path > summary:hover {{ background:var(--panel-2); }}
  details.path > summary code {{ color:var(--code); flex:1; word-break:break-all; }}
  .path-meta {{ color:var(--muted); white-space:nowrap; }}
  .path-meta b {{ color:var(--text); }}
  details.path table {{ margin:0; border-top:1px solid var(--border); }}
  /* 慢 SQL 明细表：SQL 语句列左对齐并允许换行，其余列保持数值右对齐 */
  .slow-sql-wrap table td:nth-child(5) {{ text-align:left; word-break:break-all; }}
  .slow-sql-wrap table td:first-child {{ white-space:nowrap; }}
  .slow-sql-wrap table td:nth-child(4) {{ font-variant-numeric:tabular-nums; }}
  .footer {{ max-width:1200px; margin:24px auto 0; color:var(--muted); font-size:12px; }}
  .footer a {{ color:var(--accent); }}
  @media (max-width:720px) {{
    .path-meta {{ display:none; }}
    .card-value {{ font-size:18px; }}
  }}
</style>
</head>
<body>
<header>
  <h1>指标总览 · {escape(service)}</h1>
  <div class="meta">生成时间：{generated_at} ｜ 服务：{escape(service)} ｜ <a href="/metrics?format=text">原始 Prometheus 文本</a> ｜ <a href="/metrics?format=html">刷新</a></div>
  <div class="toolbar">
    <button class="btn" id="toggle-all" type="button">全部折叠</button>
    <button class="btn" id="theme-toggle" type="button">切换主题</button>
  </div>
</header>
<div class="cards">{_render_overview_cards(flat_metrics)}</div>
<nav>{nav_items}</nav>
{sections}
<div class="footer">指标来源：GET /metrics（Prometheus 文本格式，由 Prometheus/Grafana 采集时不受影响）｜ 点击模块徽章或接口可折叠明细｜ 自定义指标分组通过 SPI 注册（MetricGroupProviderRegistry）</div>
<script>
(function () {{
  var THEME_KEY = 'metrics-theme';
  var html = document.documentElement;
  // 用户上次选择优先；否则使用服务端按系统时间生成的默认主题
  var current = localStorage.getItem(THEME_KEY) || html.getAttribute('data-theme') || 'light';
  html.setAttribute('data-theme', current);
  function themeLabel(t) {{ return t === 'dark' ? '☀ 日间模式' : '🌙 夜间模式'; }}
  var themeBtn = document.getElementById('theme-toggle');
  themeBtn.textContent = themeLabel(current);
  themeBtn.addEventListener('click', function () {{
    var next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem(THEME_KEY, next);
    themeBtn.textContent = themeLabel(next);
  }});
  // 一键展开 / 折叠全部：作用于分组、模块与接口三级折叠
  var allExpanded = true;
  var toggleBtn = document.getElementById('toggle-all');
  toggleBtn.textContent = '全部折叠';
  toggleBtn.addEventListener('click', function () {{
    allExpanded = !allExpanded;
    document.querySelectorAll('details.group, details.svc, details.path').forEach(function (d) {{
      d.open = allExpanded;
    }});
    toggleBtn.textContent = allExpanded ? '全部折叠' : '全部展开';
  }});
}})();
</script>
</body>
</html>"""
