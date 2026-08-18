"""
并发访问能力远程探针（集群视图）

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 远程探针（设计文档《并发访问能力评估设计.md》§6）：httpx 拉取其他实例
              /metrics（OpenMetrics 文本，prometheus_client.parser 解析，核心依赖自带），
              差分算各实例 QPS 并聚合集群视图。QPS 差分两种模式（§6，diff_interval 控制）：
              - 0（默认）快照差分：每次评估对每个 target 拉取一次并缓存 (counter, 时间戳)，
                下轮用真实时间戳差值差分（规避调度抖动）；
              - >0 独立差分：一次评估内连续拉两次，中间 asyncio.sleep(diff_interval)。
              多 target 并发拉取（asyncio.gather），单实例失败/超时只标记该实例不阻断整体
              （实例级失败隔离）；超时/重试/响应体上限均收敛于 RemoteProbeConfig（§6.1）。
"""
from __future__ import annotations

import asyncio
import threading
import time

import httpx
from prometheus_client.parser import text_string_to_metric_families

from web_infra.capabilities.capacity.capacity_config import RemoteProbeConfig
from web_infra.capabilities.capacity.report import ClusterSnapshot, InstanceSnapshot

# 差分 QPS 使用的指标名（与 infra.monitoring.metrics 定义一致）
_COUNTER_REQUESTS = "http_requests_total"

# 实例状态
_STATUS_OK = "ok"
_STATUS_UNREACHABLE = "unreachable"


class RemoteProbe:
    """远程探针：并发拉取集群实例 /metrics，差分 QPS 并聚合集群视图"""

    def __init__(
        self,
        config: RemoteProbeConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """初始化探针。

        :param config: 远程探针配置（超时/重试/差分模式/响应体上限）
        :param transport: httpx 传输层（测试注入 MockTransport；None 用默认网络传输）
        """
        self._config = config
        self._transport = transport
        # 每 target 的上次采样快照（counter, perf_counter 时间戳），供快照差分复用。
        # 锁保护：evaluate 为 async，但单线程事件循环内 read-modify-write 也可能被
        # 多线程调用（CLI 场景与运行实例并行），加锁保证差分基线一致性
        self._last_snapshot: dict[str, tuple[float, float]] = {}
        self._snapshot_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    async def evaluate(self, targets: tuple[str, ...]) -> ClusterSnapshot:
        """评估集群：并发拉取全部 target，聚合 QPS 分布与可达性。

        :param targets: 集群实例 /metrics 地址列表
        :return: 集群快照（实例状态/QPS/总数/不可达数）；targets 为空时返回空快照
        """
        if not targets:
            return ClusterSnapshot()
        results = await asyncio.gather(
            *(self._evaluate_target(url) for url in targets),
            return_exceptions=True,
        )
        instances: list[InstanceSnapshot] = []
        for url, result in zip(targets, results):
            if isinstance(result, Exception):
                instances.append(InstanceSnapshot(url=url, status=_STATUS_UNREACHABLE, error=str(result)))
            else:
                instances.append(result)

        ok_instances = [i for i in instances if i.status == _STATUS_OK and i.qps is not None]
        total_qps = round(sum(i.qps for i in ok_instances), 2) if ok_instances else None
        return ClusterSnapshot(
            instances=tuple(instances),
            total_qps=total_qps,
            instance_count=len(instances),
            unreachable_count=len([i for i in instances if i.status == _STATUS_UNREACHABLE]),
        )

    # ------------------------------------------------------------------
    # 内部：单目标拉取与差分
    # ------------------------------------------------------------------

    async def _evaluate_target(self, url: str) -> InstanceSnapshot:
        """拉取单目标并差分 QPS。

        首次拉取（无基线）返回 ok 但 qps=None（数据不足）；快照差分模式下
        由下次调用提供差分基线，因此单次调用可能 qps 为 None（报告标注数据不足）。
        """
        if self._config.diff_interval > 0:
            return await self._evaluate_target_independent_diff(url)
        return await self._evaluate_target_snapshot_diff(url)

    async def _evaluate_target_snapshot_diff(self, url: str) -> InstanceSnapshot:
        """快照差分：拉取一次，与上次缓存快照差分（时间差取真实时间戳）。"""
        counter, ok = await self._fetch_counter(url)
        if not ok:
            return InstanceSnapshot(url=url, status=_STATUS_UNREACHABLE)
        now = time.perf_counter()
        with self._snapshot_lock:
            previous = self._last_snapshot.get(url)
            self._last_snapshot[url] = (counter, now)
        if previous is None:
            return InstanceSnapshot(url=url, status=_STATUS_OK, qps=None)
        prev_counter, prev_ts = previous
        delta_time = now - prev_ts
        delta_count = counter - prev_counter
        qps = round(delta_count / delta_time, 2) if delta_time > 0 and delta_count >= 0 else None
        return InstanceSnapshot(url=url, status=_STATUS_OK, qps=qps)

    async def _evaluate_target_independent_diff(self, url: str) -> InstanceSnapshot:
        """独立差分：连续拉两次，中间 sleep(diff_interval)（瞬时 QPS，采样间隔过长时使用）。"""
        counter1, ok1 = await self._fetch_counter(url)
        if not ok1:
            return InstanceSnapshot(url=url, status=_STATUS_UNREACHABLE)
        await asyncio.sleep(max(self._config.diff_interval, 0.0))
        counter2, ok2 = await self._fetch_counter(url)
        if not ok2:
            # 第二次失败：仍可达但无差分数据（保持首次快照缓存供后续复用）
            return InstanceSnapshot(url=url, status=_STATUS_UNREACHABLE, error="第二次差分拉取失败")
        delta_count = counter2 - counter1
        qps = round(delta_count / self._config.diff_interval, 2) if delta_count >= 0 else None
        return InstanceSnapshot(url=url, status=_STATUS_OK, qps=qps)

    async def _fetch_counter(self, url: str) -> tuple[float | None, bool]:
        """拉取目标 /metrics 并解析 http_requests_total 总和。

        响应体流式读取（httpx AsyncClient.stream）：边读边累计字节数，超过
        max_response_bytes 立即中断（不先缓冲全量再检查，防超大响应占用内存）。

        :return: (counter 总和, 是否成功)；失败原因以异常向上抛（由调用方转为不可达标记）。
        """
        try:
            timeout = httpx.Timeout(
                connect=self._config.connect_timeout,
                read=self._config.read_timeout,
                write=self._config.write_timeout,
                pool=self._config.pool_timeout,
            )

            async def _collect() -> bytes:
                """流式读取响应体（client.stream 返回异步上下文管理器，非 awaitable）。
                边读边累计字节数，超过 max_response_bytes 立即中断（不先缓冲全量再检查，
                防超大响应占用内存）。
                """
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise ValueError(f"返回 HTTP {response.status_code}，目标 /metrics 端点异常？")
                    total_bytes = 0
                    chunks: list[bytes] = []
                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > self._config.max_response_bytes:
                            raise ValueError(
                                f"响应体超限（>{self._config.max_response_bytes} 字节），按解析失败处理"
                            )
                        chunks.append(chunk)
                    return b"".join(chunks)

            async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
                # 总耗时上限覆盖整个请求（连接 + 读取），防极端卡死
                body = await asyncio.wait_for(_collect(), timeout=self._config.timeout)
        except (httpx.TimeoutException, asyncio.TimeoutError):
            raise ValueError("请求超时（连接/读取超时，网络可达性异常？）")
        except httpx.ConnectError:
            raise ValueError("连接失败（目标端口是否监听？）")
        except ValueError:
            raise
        except Exception as exc:  # 其他网络/解析前异常
            raise ValueError(f"请求异常：{exc}")

        try:
            text = body.decode("utf-8", errors="replace")
        except Exception:
            raise ValueError("响应体解码失败")

        total: float = 0.0
        try:
            for metric_family in text_string_to_metric_families(text):
                for sample in metric_family.samples:
                    if sample.name == _COUNTER_REQUESTS:
                        total += float(sample.value)
        except Exception:
            raise ValueError("响应不是合法的 Prometheus 文本格式")
        return total, True
