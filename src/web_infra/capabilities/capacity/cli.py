"""
容量评估 CLI 命令行入口

@Author: 花海
@Date: 2026/08/18 09:00
@Description: CLI 入口（设计文档《并发访问能力评估设计.md》§7.3）：`python -m
              web_infra.capabilities.capacity [--json] [--remote]`。加载配置
              （Settings.default_source()，无需启动应用）构造评估器，输出静态估算
              （+ 可选集群视图）。**不做运行时推断**（无运行进程，运行时区标注「未运行」）；
              远程探针复用 RemoteProbe 同一失败模型（超时/重试/差分/响应体上限与运行时一致）。
              退出码：0 评估完成（含部分实例不可达）；2 全部 remote_targets 不可达
              （§6.2，供 CI 识别集群视图整体不可用）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Sequence

from web_infra.capabilities.capacity.assessor import CapacityAssessor
from web_infra.capabilities.capacity.capacity_config import CapacityConfig, DiagnosticAccessConfig, RemoteProbeConfig
from web_infra.capabilities.capacity.report import CapacityReport
from web_infra.infra.config.settings import Settings

# 退出码（§6.2）：0 评估完成；2 全部 remote_targets 不可达
EXIT_OK = 0
EXIT_ALL_UNREACHABLE = 2


def _build_config(settings: Settings) -> CapacityConfig:
    """从配置门面构造 CapacityConfig（缺失字段回落模型默认值，与装配路径一致）。"""
    remote = RemoteProbeConfig(
        connect_timeout=settings.get_float("app.capacity.remote.connect_timeout", 3.0) or 3.0,
        read_timeout=settings.get_float("app.capacity.remote.read_timeout", 5.0) or 5.0,
        write_timeout=settings.get_float("app.capacity.remote.write_timeout", 5.0) or 5.0,
        pool_timeout=settings.get_float("app.capacity.remote.pool_timeout", 5.0) or 5.0,
        timeout=settings.get_float("app.capacity.remote.timeout", 10.0) or 10.0,
        max_retries=int(settings.get("app.capacity.remote.max_retries", 0) or 0),
        diff_interval=settings.get_float("app.capacity.remote.diff_interval", 0.0) or 0.0,
        max_response_bytes=int(settings.get("app.capacity.remote.max_response_bytes", 10 * 1024 * 1024) or 0),
    )
    return CapacityConfig(
        enabled=True,
        cpu_cores=settings.get_int("app.capacity.cpu_cores", 0) or None,
        memory_mb=settings.get_int("app.capacity.memory_mb", 0) or None,
        workload_type=settings.get("app.capacity.workload_type", "io_intensive") or "io_intensive",
        io_concurrency_factor=int(settings.get("app.capacity.io_concurrency_factor", 25) or 25),
        assumed_avg_latency_ms=settings.get_float("app.capacity.assumed_avg_latency_ms", 200.0) or 200.0,
        safe_ratio=settings.get_float("app.capacity.safe_ratio", 0.7) or 0.7,
        slo_alert_ratio=settings.get_float("app.capacity.slo_alert_ratio", 0.8) or 0.8,
        slo_target_availability=settings.get_float("app.capacity.slo_target_availability", 0.99) or 0.99,
        sample_window=int(settings.get("app.capacity.sample_window", 60) or 60),
        sample_interval=settings.get_float("app.capacity.sample_interval", 5.0) or 5.0,
        remote=remote,
        remote_targets=tuple(settings.get("app.capacity.remote_targets") or ()),
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """解析 CLI 参数（--json / --remote）"""
    parser = argparse.ArgumentParser(
        prog="web_infra.capabilities.capacity",
        description="并发访问能力评估：静态估算（+ 可选集群视图）。",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON（默认文本报告）")
    parser.add_argument("--remote", action="store_true", help="附加集群视图（需配置 app.capacity.remote_targets）")
    return parser.parse_args(argv)


def _render_text(report) -> str:
    """渲染文本报告（默认输出格式）"""
    static = report.static
    lines = [
        f"生成时间: {report.generated_at}",
        "--- 静态估算 ---",
        f"CPU 核数: {static.cpu_cores} | 平均响应时间假设: {static.assumed_avg_latency_ms}ms",
        f"整体并发上限: {static.concurrency_limit or 'N/A'}",
    ]
    for c in static.components:
        lines.append(f"  - {c.name}: {c.concurrency_limit or 'N/A'} ({c.description})")
    lines.append(f"瓶颈组件: {static.bottleneck or 'N/A'}")
    lines.append(f"理论 QPS: {static.theoretical_max_qps or 'N/A'}")
    lines.append(f"安全水位 QPS: {static.safe_qps or 'N/A'}")
    lines.append(
        f"限流 QPS: {static.rate_limit_qps or '未启用'} | 生效最大 QPS: "
        f"{static.effective_max_qps or 'N/A'} | 受限于限流: {static.rate_limit_limited}"
    )
    lines.append("--- 运行时 ---")
    lines.append("未运行（CLI 仅静态估算；运行值经已运行实例 /capacity 或 /metrics 获取）")
    if report.cluster is not None and report.cluster.instance_count > 0:
        lines.append("--- 集群视图 ---")
        lines.append(
            f"实例数: {report.cluster.instance_count} | 不可达: {report.cluster.unreachable_count} | "
            f"集群总 QPS: {report.cluster.total_qps or 'N/A'}"
        )
        for i in report.cluster.instances:
            lines.append(f"  - {i.url}: {i.status}" + (f" (qps={i.qps})" if i.qps is not None else "") + (f" {i.error}" if i.error else ""))
    lines.append("--- 建议 ---")
    lines.extend(f"  - {s}" for s in report.suggestions)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主入口：解析参数、构造评估器、输出报告，返回进程退出码。

    :param argv: 命令行参数（默认 sys.argv[1:]）
    :return: 退出码（0 完成 / 2 全部不可达）
    """
    args = _parse_args(argv)
    settings = Settings.instance()  # 全局 Settings（默认源 = 环境变量 > application.yml > 框架默认 yml）
    config = _build_config(settings)
    assessor = CapacityAssessor(settings, config)

    async def _run() -> tuple[int, object]:
        # CLI 不做运行时推断（§7.3）：静态估算 + 可选集群视图（远程拉取）
        report = assessor.assess_static_only()
        if args.remote:
            cluster = await assessor._probe.evaluate(assessor._config.remote_targets)
            report = CapacityReport(
                generated_at=report.generated_at,
                static=report.static,
                runtime=None,
                cluster=cluster,
                utilization_ratio=None,
                suggestions=report.suggestions,
            )
        if report.cluster is not None and report.cluster.all_unreachable:
            print("remote_targets 全部不可达，请检查网络与地址配置", file=sys.stderr)
            return EXIT_ALL_UNREACHABLE, report
        return EXIT_OK, report

    exit_code, report = asyncio.run(_run())
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(_render_text(report))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
