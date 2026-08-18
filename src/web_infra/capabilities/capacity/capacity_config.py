"""
并发访问能力评估配置模型

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 容量评估配置（app.capacity 段）与诊断端点访问控制配置（app.diagnostics.access 段）。
              默认值与设计文档《并发访问能力评估设计.md》§10 收敛一致；装配时由 Application
              经 Settings 读取对应配置段构造，缺失字段回落本模型默认值（框架不散落默认值
              于装配代码，业务侧 application.yml 可覆盖）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from web_infra.infra.web.diagnostic_access import DEFAULT_ALLOWED_CIDRS

# IO 密集单核并发系数默认值（§4.2：经验值，可运行时用「当前并发」反推校准）
DEFAULT_IO_CONCURRENCY_FACTOR = 25


@dataclass(frozen=True)
class RemoteProbeConfig:
    """远程探针配置（app.capacity.remote，§6.1）

    :param connect_timeout: 连接超时（秒，httpx connect 阶段）
    :param read_timeout: 读取超时（秒，httpx read 阶段）
    :param write_timeout: 写入超时（秒，httpx write 阶段；GET 无请求体影响小）
    :param pool_timeout: 连接池等待超时（秒，httpx pool 阶段）
    :param timeout: 总耗时上限（秒，asyncio.wait_for 包裹整体请求，覆盖极端卡死）
    :param max_retries: 重试次数（默认 0：失败下轮采样天然重试）
    :param diff_interval: QPS 差分间隔（秒）；0=快照差分（复用采样周期，时间差取真实时间戳），
        >0=独立差分（探针内连续拉两次，中间 sleep(diff_interval)）
    :param max_response_bytes: 响应体大小上限（字节，默认 10MB），超限按解析失败处理
    """

    connect_timeout: float = 3.0
    read_timeout: float = 5.0
    write_timeout: float = 5.0
    pool_timeout: float = 5.0
    timeout: float = 10.0
    max_retries: int = 0
    diff_interval: float = 0.0
    max_response_bytes: int = 10 * 1024 * 1024


@dataclass(frozen=True)
class CapacityConfig:
    """容量评估配置（app.capacity 段，§10）

    :param enabled: 是否启用评估能力（注册 /capacity 端点 + 启动采样任务）
    :param cpu_cores: 覆盖自动探测的 CPU 核数；None 用 os.cpu_count()
    :param memory_mb: 覆盖自动探测的内存（MB）；None 探测失败跳过（本期仅报告占位）
    :param workload_type: io_intensive（默认）/ cpu_intensive
    :param io_concurrency_factor: IO 密集单核并发系数（默认 25）
    :param assumed_avg_latency_ms: Little's Law 的平均响应时间假设（毫秒，默认 200）
    :param safe_ratio: 安全水位系数（默认 0.7）
    :param slo_alert_ratio: SLO 错误率预警阈值系数（默认 0.8）
    :param slo_target_availability: SLO 目标可用性（默认 0.99，用于允许错误率反推）
    :param sample_window: 运行时滑动窗口秒数（默认 60）
    :param sample_interval: 采样间隔秒数（默认 5）
    :param remote: 远程探针配置（app.capacity.remote 段）
    :param remote_targets: 集群其他实例 /metrics 地址列表；空则只评估本实例
    """

    enabled: bool = False
    cpu_cores: int | None = None
    memory_mb: int | None = None
    workload_type: str = "io_intensive"
    io_concurrency_factor: int = DEFAULT_IO_CONCURRENCY_FACTOR
    assumed_avg_latency_ms: float = 200.0
    safe_ratio: float = 0.7
    slo_alert_ratio: float = 0.8
    slo_target_availability: float = 0.99
    sample_window: int = 60
    sample_interval: float = 5.0
    remote: RemoteProbeConfig = field(default_factory=RemoteProbeConfig)
    remote_targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiagnosticAccessConfig:
    """诊断端点访问控制配置（app.diagnostics.access，§9）

    :param enabled: 生产环境默认启用 IP 白名单；dev/test/stage 忽略（生效条件还要求 app_env==prod）
    :param allowed_cidrs: 追加白名单 CIDR（默认仅精确 5 段 DEFAULT_ALLOWED_CIDRS）
    """

    enabled: bool = True
    allowed_cidrs: tuple[str, ...] = ()

    def effective_cidrs(self) -> tuple[str, ...]:
        """生效白名单 = 默认精确 5 段 + 追加 CIDR（去重保序）"""
        merged = list(DEFAULT_ALLOWED_CIDRS)
        for cidr in self.allowed_cidrs:
            if cidr not in merged:
                merged.append(cidr)
        return tuple(merged)
