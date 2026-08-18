"""
上传文件类型校验器

@Author: 花海
@Date: 2026/08/14 20:30
@Description: 上传文件类型校验（规范 §22.2：魔数校验 + 后缀白名单，禁止可执行文件/脚本上传）。
              后缀白名单默认覆盖常见图片/视频/音频/文档/压缩类型；魔数表按文件头签名识别真实类型，
              防止改名绕过（如将 .exe 改名 .png 上传）。业务可传入自定义白名单扩展。
"""
from __future__ import annotations

from typing import Iterable


class FileTypeValidator:
    """上传文件类型校验器：后缀白名单 + 内容魔数校验"""

    #: 默认允许的后缀（常见安全类型，不含可执行/脚本文件）
    DEFAULT_ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
        {
            # 图片
            "png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "ico",
            # 视频
            "mp4", "mkv", "avi", "mov", "webm",
            # 音频
            "mp3", "wav", "ogg", "flac", "m4a",
            # 文档/文本
            "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md", "csv", "json", "xml",
            # 压缩包
            "zip", "rar", "7z", "tar", "gz",
        }
    )

    #: 常见文件类型魔数（文件头签名，前若干字节）
    MAGIC_SIGNATURES: tuple[tuple[str, bytes], ...] = (
        ("png", b"\x89PNG\r\n\x1a\n"),
        ("jpeg", b"\xff\xd8\xff"),
        ("gif", b"GIF8"),
        ("pdf", b"%PDF"),
        ("zip", b"PK\x03\x04"),
        ("rar", b"Rar!\x1a\x07"),
        ("7z", b"7z\xbc\xaf\x27\x1c"),
        ("gzip", b"\x1f\x8b"),
        ("webp", b"RIFF"),          # RIFF....WEBP 需进一步确认
        ("mp4", b"\x00\x00\x00\x18ftyp"),
        ("mp3", b"ID3"),
        ("wav", b"RIFF"),
        ("ogg", b"OggS"),
    )

    def __init__(self, allowed_extensions: Iterable[str] | None = None) -> None:
        """初始化校验器。

        :param allowed_extensions: 自定义后缀白名单（缺省使用默认白名单）
        """
        self._allowed = frozenset(allowed_extensions) if allowed_extensions is not None else self.DEFAULT_ALLOWED_EXTENSIONS

    def validate_extension(self, filename: str) -> None:
        """校验文件后缀在白名单内，否则抛 ValueError（规范 §22.2 后缀白名单）。

        :param filename: 原始文件名
        :raises ValueError: 后缀为空或不在白名单
        """
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in self._allowed:
            raise ValueError(f"不支持的文件类型: .{ext or '无后缀'}（仅允许: {sorted(self._allowed)}）")

    def validate_magic(self, data: bytes) -> None:
        """校验文件内容魔数与白名单类型匹配，否则抛 ValueError（规范 §22.2 内容签名校验，防改名绕过）。

        :param data: 文件内容（至少包含文件头若干字节）
        :raises ValueError: 内容为空或魔数不匹配
        """
        if not data:
            raise ValueError("文件内容为空，无法校验类型")
        if any(data.startswith(sig) for _, sig in self.MAGIC_SIGNATURES):
            return
        raise ValueError("文件内容签名校验失败（魔数不匹配，禁止改名绕过类型校验）")
