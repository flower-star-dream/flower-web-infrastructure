"""
本地磁盘分片存储

@Author: 花海
@Date: 2026/08/14 19:30
@Description: 基于本地临时目录的分片存储（规范 §22.4 默认实现）：
              分片落盘 `{base_dir}/{upload_id}/part_{n}`，合并按序拼接并清理分片；
              提供按目录 mtime 的过期分片目录清理（规范 §22.4 临时目录 TTL）。
              面向小中型文件与单实例场景；大文件生产场景使用 MinioPartStorage。
"""
from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime


class LocalPartStorage:
    """本地磁盘分片存储（默认实现）"""

    def __init__(self, base_dir: str) -> None:
        """初始化分片存储。

        :param base_dir: 分片临时目录（规范 §22.4：临时目录 TTL 由独立定时作业清理）
        """
        self._base_dir = base_dir

    def _task_dir(self, upload_id: str) -> str:
        """任务分片目录"""
        return os.path.join(self._base_dir, upload_id)

    def _part_path(self, upload_id: str, part_number: int) -> str:
        """单个分片文件路径"""
        return os.path.join(self._task_dir(upload_id), f"part_{part_number}")

    async def save_part(self, upload_id: str, part_number: int, data: bytes) -> None:
        """保存分片（同分片重传覆盖，幂等）"""
        def _write() -> None:
            os.makedirs(self._task_dir(upload_id), exist_ok=True)
            with open(self._part_path(upload_id, part_number), "wb") as f:
                f.write(data)

        await asyncio.to_thread(_write)

    async def list_parts(self, upload_id: str) -> list[int]:
        """列出已存在分片序号（升序，断点续传依据）"""
        def _list() -> list[int]:
            task_dir = self._task_dir(upload_id)
            if not os.path.isdir(task_dir):
                return []
            parts = []
            for name in os.listdir(task_dir):
                if name.startswith("part_"):
                    try:
                        parts.append(int(name[len("part_"):]))
                    except ValueError:
                        continue
            return sorted(parts)

        return await asyncio.to_thread(_list)

    async def read_part(self, upload_id: str, part_number: int) -> bytes:
        """读取单个分片内容（MD5 合并校验）"""
        def _read() -> bytes:
            with open(self._part_path(upload_id, part_number), "rb") as f:
                return f.read()

        return await asyncio.to_thread(_read)

    async def merge(self, upload_id: str, object_key: str) -> int:
        """按分片序号合并为完整文件，返回合并后大小（字节）；合并后清理分片"""
        def _merge() -> int:
            parts = [p for p in os.listdir(self._task_dir(upload_id)) if p.startswith("part_")]
            parts.sort(key=lambda n: int(n[len("part_"):]))
            merged_path = os.path.join(self._base_dir, f"{upload_id}.merged")
            total = 0
            with open(merged_path, "wb") as out:
                for name in parts:
                    with open(os.path.join(self._task_dir(upload_id), name), "rb") as f:
                        data = f.read()
                        out.write(data)
                        total += len(data)
            shutil.rmtree(self._task_dir(upload_id), ignore_errors=True)
            return total

        return await asyncio.to_thread(_merge)

    async def remove_task(self, upload_id: str) -> None:
        """清理任务全部分片与合并临时文件（合并后/取消时）"""
        def _rm() -> None:
            shutil.rmtree(self._task_dir(upload_id), ignore_errors=True)
            merged = os.path.join(self._base_dir, f"{upload_id}.merged")
            if os.path.exists(merged):
                os.remove(merged)

        await asyncio.to_thread(_rm)

    async def cleanup_expired(self, before: datetime) -> int:
        """清理 mtime 早于 before 的过期分片临时目录，返回清理数（规范 §22.4：临时目录 TTL 清理）。

        :param before: 过期时间点（按目录 mtime 判定；epoch 比较与时区无关）
        """
        def _cleanup() -> int:
            if not os.path.isdir(self._base_dir):
                return 0
            threshold = before.timestamp()
            removed = 0
            for name in os.listdir(self._base_dir):
                path = os.path.join(self._base_dir, name)
                if not os.path.isdir(path):
                    continue
                try:
                    if os.path.getmtime(path) < threshold:
                        shutil.rmtree(path, ignore_errors=True)
                        removed += 1
                except OSError:
                    continue
            return removed

        return await asyncio.to_thread(_cleanup)
