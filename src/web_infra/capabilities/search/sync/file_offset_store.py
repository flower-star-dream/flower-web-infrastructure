"""
本地文件位点存储

@Author: 花海
@Date: 2026/08/22 15:00
@Description: CDC 位点存储本地文件实现（搜索引擎数据同步方案 §5.3）：JSON 文件集中保存位点，
              无外部依赖，适合单实例/测试场景；多实例须配合分布式锁选主（实例间不共享位点）。
              异步写经 asyncio.to_thread 避免阻塞事件循环。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

from web_infra.capabilities.search.sync.cdc_offset_store_interface import CdcOffsetStoreInterface
from web_infra.infra.utils.file_lock import FileLock

logger = logging.getLogger("web_infra.capabilities.search.sync.file_offset_store")

#: 默认位点文件路径（项目根 data 目录下）
_DEFAULT_OFFSET_FILE = "data/search-sync-offsets.json"


class FileOffsetStore(CdcOffsetStoreInterface):
    """本地文件位点存储（JSON，单实例/测试场景）

    :param path: 位点文件路径（缺省 data/search-sync-offsets.json）
    """

    def __init__(self, path: str | os.PathLike[str] = _DEFAULT_OFFSET_FILE) -> None:
        """初始化文件位点存储。

        :param path: 位点文件路径
        """
        self._path = Path(path)
        self._name = "file"

    @property
    def name(self) -> str:
        """数据源标识（供错误码/指标区分）"""
        return self._name

    async def save(self, key: str, position: str) -> None:
        """持久化位点：读取现有 JSON → 更新键值 → 原子写回（临时文件 + 改名）"""
        await asyncio.to_thread(self._write, key, position)

    async def load(self, key: str) -> str | None:
        """读取位点；文件不存在或无记录返回 None"""
        return await asyncio.to_thread(self._read, key)

    # ------------------------------------------------------------------
    # 同步辅助（asyncio.to_thread 调用，避免阻塞事件循环）
    # ------------------------------------------------------------------

    def _write(self, key: str, position: str) -> None:
        """同步写位点（临时文件 + 原子改名，防进程中断损坏）"""
        self._parent_dir().mkdir(parents=True, exist_ok=True)
        data: dict[str, str] = {}
        with FileLock(str(self._path) + ".lock"):
            if self._path.exists():
                try:
                    data = json.loads(self._path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):  # noqa: PERF203 - 损坏文件重写
                    logger.warning("offset_file_corrupt reset_path=%s", self._path)
                    data = {}
            data[key] = position
            self._atomic_dump(data)

    def _read(self, key: str) -> str | None:
        """同步读位点；文件损坏则告警并返回 None（走全量对账兜底）"""
        if not self._path.exists():
            return None
        with FileLock(str(self._path) + ".lock"):
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("offset_file_corrupt_reset path=%s error=%s", self._path, exc)
                return None
            value = data.get(key)
            return str(value) if value is not None else None

    def _atomic_dump(self, data: dict[str, str]) -> None:
        """原子写：先写临时文件再改名替换，避免半写文件"""
        fd, tmp_path = tempfile.mkstemp(dir=str(self._parent_dir()), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            os.replace(tmp_path, self._path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _parent_dir(self) -> Path:
        """位点文件的父目录"""
        return self._path.parent
