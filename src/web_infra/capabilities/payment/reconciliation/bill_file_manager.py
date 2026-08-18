"""
渠道账单文件管理器（BillFileManager）

@Author: 花海
@Date: 2026/08/17
@Description: 渠道账单文件生命周期管理（规范 §6.7）：账单是对账与审计的权威凭证——
              下载后必须校验完整性（文件头/长度/校验和），校验失败丢弃并告警重下；
              按账期组织存储（独立目录/桶），保留期与流水追溯窗口一致（≥ 90 天）过期归档清理；
              文件缺失/损坏支持从渠道重新下载并保留下载记录；默认本地目录实现，
              生产按 ObjectStorageInterface 扩展为独立对象存储（§6.7 存储位置）。
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger("web_infra.capabilities.payment.reconciliation")


class BillFileManager:
    """渠道账单文件管理器（校验/存储/归档，§6.7）"""

    def __init__(self, base_dir: str | Path, *, retain_days: int = 90,
                 expected_header: str | None = None, expected_length: int | None = None) -> None:
        """初始化账单文件管理器。

        :param base_dir: 账单根目录（按账期子目录组织：base/{channel}/{biz_date}/）
        :param retain_days: 账单保留期（天，§6.7：与流水追溯窗口一致 ≥ 90 天）
        :param expected_header: 账单文件头校验（渠道规范，缺失即完整性校验失败）
        :param expected_length: 账单文件长度下限校验（字节，防空文件/截断）
        """
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._retain_days = retain_days
        self._expected_header = expected_header
        self._expected_length = expected_length

    def save(self, channel: str, biz_date: date, content: bytes, *, checksum: str | None = None) -> Path:
        """保存账单文件（校验完整性 → 按账期落盘）。

        :param channel: 渠道名
        :param biz_date: 账期（T-1）
        :param content: 账单文件内容（字节）
        :param checksum: 渠道提供的校验和（可选，sha256 十六进制；不匹配视为校验失败）
        :return: 落盘路径
        :raises ValueError: 完整性校验失败（文件头不符/长度不足/校验和不匹配）→ 丢弃并告警重下（§6.7）
        """
        self._validate(content, checksum)
        bill_dir = self._bill_dir(channel, biz_date)
        bill_dir.mkdir(parents=True, exist_ok=True)
        path = bill_dir / self._file_name(channel, biz_date)
        path.write_bytes(content)
        logger.info("bill_file_saved channel=%s biz_date=%s size=%s path=%s", channel, biz_date, len(content), path)
        return path

    def load(self, channel: str, biz_date: date) -> bytes | None:
        """读取账单文件（缺失返回 None，触发重新下载并记录，§6.7）"""
        path = self._bill_dir(channel, biz_date) / self._file_name(channel, biz_date)
        if not path.exists():
            logger.warning("bill_file_missing channel=%s biz_date=%s（缺失，需从渠道重新下载，§6.7）", channel, biz_date)
            return None
        content = path.read_bytes()
        try:
            self._validate(content, None)
        except ValueError:
            logger.error("bill_file_corrupted channel=%s biz_date=%s（校验失败，丢弃重下，§6.7）", channel, biz_date)
            path.unlink(missing_ok=True)
            return None
        return content

    def cleanup_expired(self, *, today: date | None = None) -> int:
        """清理过期账单（§6.7 保留期：保留期外归档/清理；与流水表保留策略一致）"""
        today = today or date.today()
        cutoff = today - timedelta(days=self._retain_days)
        removed = 0
        for channel_dir in self._base_dir.iterdir():
            if not channel_dir.is_dir():
                continue
            for biz_date_dir in channel_dir.iterdir():
                if not biz_date_dir.is_dir():
                    continue
                try:
                    biz_date = date.fromisoformat(biz_date_dir.name)
                except ValueError:
                    continue
                if biz_date < cutoff:
                    for f in biz_date_dir.iterdir():
                        f.unlink(missing_ok=True)
                        removed += 1
                    biz_date_dir.rmdir()
        if removed:
            logger.info("bill_file_cleanup_removed=%s cutoff=%s（保留期 %s 天，§6.7）", removed, cutoff, self._retain_days)
        return removed

    # ------------------------------------------------------------------
    # 内部：校验与路径
    # ------------------------------------------------------------------

    def _validate(self, content: bytes, checksum: str | None) -> None:
        """账单文件完整性校验（§6.7）：文件头/长度/校验和，失败抛 ValueError"""
        if self._expected_length is not None and len(content) < self._expected_length:
            raise ValueError(f"账单文件长度不足：{len(content)} < {self._expected_length}（§6.7 完整性校验失败）")
        if self._expected_header is not None and not content.startswith(self._expected_header.encode()):
            raise ValueError(f"账单文件头不符：期望 {self._expected_header!r}（§6.7 完整性校验失败）")
        if checksum:
            actual = hashlib.sha256(content).hexdigest()
            if actual != checksum.lower():
                raise ValueError(f"账单校验和不匹配（§6.7 完整性校验失败，丢弃重下）")

    def _bill_dir(self, channel: str, biz_date: date) -> Path:
        """按账期组织目录（§6.7：base/{channel}/{biz_date}/）"""
        return self._base_dir / channel / biz_date.isoformat()

    @staticmethod
    def _file_name(channel: str, biz_date: date) -> str:
        """账单文件名（渠道 + 账期，可追溯）"""
        return f"{channel}_{biz_date.isoformat()}.bill"
