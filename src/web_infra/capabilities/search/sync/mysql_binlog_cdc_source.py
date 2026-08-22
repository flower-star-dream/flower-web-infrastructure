"""
MySQL binlog CDC 数据源

@Author: 花海
@Date: 2026/08/22 15:00
@Description: MySQL binlog CDC 数据源默认实现（搜索引擎数据同步方案 §5.2）：基于官方
              mysql-replication 库（BinLogStreamReader，同步阻塞读）旁路消费 MySQL binlog，
              ROW 格式解析 Write/Update/Delete 事件并转换为统一 CdcChangeEvent。
              同步读经 asyncio.to_thread 桥接：读线程逐事件转换为 CdcChangeEvent 后经
              run_coroutine_threadsafe 投递到事件循环调用 handler。
              依赖 cdc extra（mysql-replication>=1.0.16）：延迟导入，未安装仅启用时给出安装提示。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Coroutine, cast

from web_infra.capabilities.search.sync.cdc_change_event import CdcChangeEvent, CdcOp
from web_infra.capabilities.search.sync.cdc_offset_store_interface import CdcOffsetStoreInterface
from web_infra.capabilities.search.sync.cdc_source_interface import CdcEventHandler

logger = logging.getLogger("web_infra.capabilities.search.sync.mysql_source")

#: 位点 key 前缀（Pipeline 推进全局位点："{source}:{database}:offset"）
_OFFSET_KEY_TMPL = "mysql:{database}:offset"


class MysqlBinlogCdcSource:
    """MySQL binlog CDC 数据源（mysql-replication 库延迟导入）

    :param connection_settings: pymysql 连接参数字典（host/port/user/password/database）
    :param server_id: 伪从库 server-id（多实例必须唯一）
    :param offset_store: 位点存储（启动时读位点续读；消费推进由 Pipeline 负责）
    :param only_tables: 表监听白名单（空 = 全部，透传 BinLogStreamReader）
    :param database: 监听库（空 = 全部库，透传 only_schemas）
    :param slave_heartbeat: 心跳间隔（秒，防连接超时断开）
    :param blocking: 是否阻塞模式（False 为 EOF 后返回，True 持续阻塞；生产用 True，测试可 False）
    """

    def __init__(
        self,
        connection_settings: dict[str, Any],
        server_id: int,
        offset_store: CdcOffsetStoreInterface,
        *,
        only_tables: list[str] | None = None,
        database: str = "",
        slave_heartbeat: int = 30,
        blocking: bool = True,
    ) -> None:
        """初始化 MySQL binlog CDC 数据源。

        :param connection_settings: pymysql 连接参数字典
        :param server_id: 伪从库 server-id
        :param offset_store: 位点存储
        :param only_tables: 表监听白名单（空 = 全部）
        :param database: 监听库（空 = 全部库）
        :param slave_heartbeat: 心跳间隔（秒）
        :param blocking: 阻塞模式（生产 True）
        """
        self._connection_settings = dict(connection_settings)
        self._server_id = server_id
        self._offset_store = offset_store
        self._only_tables = list(only_tables or [])
        self._database = database
        self._slave_heartbeat = slave_heartbeat
        self._blocking = blocking
        self._name = "mysql"

        self._handler: CdcEventHandler | None = None
        self._stop_event = asyncio.Event()
        self._reader_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._log_file: str | None = None
        self._log_pos: int | None = None

    @property
    def name(self) -> str:
        """数据源标识（供错误码/指标区分）"""
        return self._name

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def subscribe(self, handler: CdcEventHandler) -> None:
        """注册事件处理器（启动前调用；覆盖已有处理器）。

        :param handler: 变更事件处理器（由 Pipeline 注入）
        """
        self._handler = handler

    async def start(self) -> None:
        """启动监听：读取已持久化位点 → 后台线程读 binlog → 逐事件投递 handler"""
        if self._handler is None:
            raise RuntimeError("MysqlBinlogCdcSource 必须先 subscribe(handler) 再 start()")
        self._loop = asyncio.get_running_loop()
        self._stop_event.clear()
        self._log_file, self._log_pos = await self._load_offset()
        self._reader_task = asyncio.create_task(self._run_reader())
        logger.info(
            "mysql_cdc_started server_id=%s log_file=%s log_pos=%s", self._server_id, self._log_file, self._log_pos
        )

    async def stop(self) -> None:
        """停止监听：中断读线程并等待退出"""
        self._stop_event.set()
        if self._reader_task is not None:
            try:
                await asyncio.wait_for(self._reader_task, timeout=5)
            except asyncio.TimeoutError:
                self._reader_task.cancel()
            self._reader_task = None
        logger.info("mysql_cdc_stopped server_id=%s", self._server_id)

    # ------------------------------------------------------------------
    # 读线程：阻塞读 binlog → 转换事件 → 回调 handler
    # ------------------------------------------------------------------

    async def _run_reader(self) -> None:
        """读协程：to_thread 跑阻塞读；连接丢失指数退避重连（重连前重读位点）"""
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self._read_events_blocking)
                backoff = 1.0  # 正常退出（blocking=False 读到 EOF）重置退避
            except Exception as exc:  # noqa: BLE001 - 统一重连治理
                if self._stop_event.is_set():
                    break
                logger.warning("mysql_cdc_reader_error error=%s next_reconnect_in=%ss", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                self._log_file, self._log_pos = await self._load_offset()  # 重连前重读位点

    def _read_events_blocking(self) -> None:
        """阻塞读取 binlog 事件（在 to_thread 线程执行）：逐个转换并同步投递 handler（背压饱和）。

        :raises ConnectionError: 连接丢失，触发上层重连
        """
        # 延迟导入：未安装 cdc extra 时给出明确安装指引
        try:
            from pymysqlreplication import BinLogStreamReader  # type: ignore[import-not-found]
            from pymysqlreplication.row_event import (  # type: ignore[import-not-found]
                DeleteRowsEvent,
                TableMapEvent,
                UpdateRowsEvent,
                WriteRowsEvent,
            )
        except ImportError as exc:
            raise ImportError(
                "MysqlBinlogCdcSource 需要安装 cdc extra：pip install 'flower-web-infrastructure[cdc]'"
            ) from exc

        stream = BinLogStreamReader(
            self._connection_settings,
            self._server_id,
            resume_stream=True,
            blocking=self._blocking,
            only_events=[WriteRowsEvent, UpdateRowsEvent, DeleteRowsEvent, TableMapEvent],
            only_tables=self._only_tables or None,
            only_schemas=[self._database] if self._database else None,
            slave_heartbeat=self._slave_heartbeat,
            use_column_name_cache=True,
        )
        try:
            for event in stream:
                if self._stop_event.is_set():
                    break
                self._log_file = getattr(event.packet, "log_file", self._log_file)
                self._log_pos = getattr(event.packet, "log_pos", self._log_pos)
                self._dispatch(event)
        except Exception as exc:  # noqa: BLE001
            raise ConnectionError(f"binlog 读取中断: {exc}") from exc
        finally:
            stream.close()

    def _dispatch(self, event: Any) -> None:
        """转换事件并同步投递 handler（线程内调用，阻塞等待事件循环处理完成——背压）"""
        change = self._to_change_event(event)
        if change is None:
            return
        assert self._handler is not None  # start() 已校验
        assert self._loop is not None  # start() 已绑定
        # handler 为 async 方法（返回 Coroutine），经 cast 收窄以匹配 run_coroutine_threadsafe 签名
        coro = cast(Coroutine[Any, Any, None], self._handler(change))
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        future.result()  # 同步等待 handler 完成（背压：事件不堆积）

    def _to_change_event(self, event: Any) -> CdcChangeEvent | None:
        """转换 binlog 事件为统一 CdcChangeEvent（Write→INSERT、Update→UPDATE、Delete→DELETE）。

        :return: CdcChangeEvent；辅助事件（TableMapEvent 等）无业务变更返回 None
        """
        database = getattr(event, "schema", "") or self._database
        table = getattr(event, "table", "")
        position = self._position_str(event)
        ts = self._to_utc(getattr(event, "timestamp", None))
        name = event.__class__.__name__
        if name == "WriteRowsEvent":
            return self._build_insert(database, table, event, position, ts)
        if name == "UpdateRowsEvent":
            return self._build_update(database, table, event, position, ts)
        if name == "DeleteRowsEvent":
            return self._build_delete(database, table, event, position, ts)
        return None

    def _build_insert(self, database: str, table: str, event: Any, position: str, ts: datetime | None) -> CdcChangeEvent | None:
        """构造 INSERT 事件（取行 values 为 after，主键从行数据提取；无有效主键返回 None）"""
        for row in event.rows:
            values = row.get("values", {})
            pk = self._extract_primary_key(event, values)
            if pk:
                return CdcChangeEvent(self._name, database, table, CdcOp.INSERT, pk, after=values, position=position, ts=ts)
        return None

    def _build_update(self, database: str, table: str, event: Any, position: str, ts: datetime | None) -> CdcChangeEvent | None:
        """构造 UPDATE 事件（before/after 镜像；主键可从 after 或 before 提取；无有效主键返回 None）"""
        for row in event.rows:
            before = row.get("before_values", {})
            after = row.get("after_values", {})
            pk = self._extract_primary_key(event, after) or self._extract_primary_key(event, before)
            if pk:
                return CdcChangeEvent(self._name, database, table, CdcOp.UPDATE, pk, before=before, after=after, position=position, ts=ts)
        return None

    def _build_delete(self, database: str, table: str, event: Any, position: str, ts: datetime | None) -> CdcChangeEvent | None:
        """构造 DELETE 事件（主键从 values 提取；无有效主键返回 None）"""
        for row in event.rows:
            values = row.get("values", {})
            pk = self._extract_primary_key(event, values)
            if pk:
                return CdcChangeEvent(self._name, database, table, CdcOp.DELETE, pk, after=values, position=position, ts=ts)
        return None

    # ------------------------------------------------------------------
    # 内部：主键提取 / 位点 / 时间
    # ------------------------------------------------------------------

    def _extract_primary_key(self, event: Any, row: dict[str, Any]) -> dict[str, Any]:
        """从行数据提取主键。

        优先用事件元数据中的主键列（column_schemas 含 primary_key 标记）；
        否则回退到疑似主键列（id/{table}_id/以 id 结尾）或单列整行。
        """
        pk_columns = self._primary_key_columns(event)
        if pk_columns:
            pk = {col: row[col] for col in pk_columns if col in row}
            if pk:
                return pk
        inferred = {k: v for k, v in row.items() if self._looks_like_pk(k)}
        if inferred:
            return inferred
        return {k: v for k, v in row.items() if len(row) == 1}

    def _primary_key_columns(self, event: Any) -> list[str]:
        """从事件的列元数据提取主键列名（column_schemas 含 primary_key 标记）"""
        columns = getattr(event, "columns", None) or getattr(event, "column_schemas", None)
        if not columns:
            return []
        pks: list[str] = []
        for col in columns:
            name = getattr(col, "name", None) or getattr(col, "column_name", None)
            is_pk = getattr(col, "primary_key", False) or getattr(col, "is_primary", False)
            if name and is_pk:
                pks.append(name)
        return pks

    @staticmethod
    def _looks_like_pk(name: str) -> bool:
        """推断疑似主键列名（id / {table}_id / 以 id 结尾）"""
        lower = name.lower()
        return lower in {"id", "uuid"} or lower.endswith("_id")

    def _position_str(self, event: Any) -> str:
        """构造位点字符串 "log_file:log_pos"（取自事件所在流位置或 reader 状态）"""
        log_file = self._log_file or ""
        log_pos = self._log_pos or 0
        return f"{log_file}:{log_pos}"

    def _to_utc(self, ts: int | None) -> datetime | None:
        """binlog 时间戳（epoch 秒）转 UTC datetime"""
        if ts is None:
            return None
        try:
            return datetime.utcfromtimestamp(int(ts))
        except (ValueError, OSError):  # pragma: no cover - 非法时间戳容错
            return None

    async def _load_offset(self) -> tuple[str | None, int | None]:
        """读取已持久化位点（log_file:log_pos）；无记录返回 (None, None) 从当前位置起读"""
        position = await self._offset_store.load(self._offset_key())
        if position and ":" in position:
            log_file, _, log_pos = position.partition(":")
            try:
                return log_file, int(log_pos)
            except ValueError:  # pragma: no cover - 位点损坏容错
                logger.warning("mysql_cdc_offset_invalid key=%s position=%s", self._offset_key(), position)
        return None, None

    def _offset_key(self) -> str:
        """位点 key（与 Pipeline 推进一致：{source}:{database}:offset）"""
        return _OFFSET_KEY_TMPL.format(database=self._database)
