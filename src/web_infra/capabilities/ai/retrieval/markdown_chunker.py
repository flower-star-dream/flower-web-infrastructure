"""
Markdown 文档切片器

@Author: 花海
@Date: 2026/08/14 15:00
@Description: Markdown 文档结构块切片（默认实现，AI 规范 §11）：
              代码块/表格作为原子块不拆分；正文按标题层级分组、空行分段；
              每个切片携带所属标题上下文。HTML/PDF 等类型可通过 DocumentChunkerInterface 扩展。
"""
from __future__ import annotations

import re

from web_infra.capabilities.ai.retrieval.chunk import Chunk
from web_infra.capabilities.ai.retrieval.document_chunker import DocumentChunkerInterface

# 标题正则：^#{1,6} 空格 + 标题文本
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# 表格分隔行（| --- | --- |）
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
# 表格行（以 | 开头）
_TABLE_ROW_RE = re.compile(r"^\s*\|")


class MarkdownChunker(DocumentChunkerInterface):
    """Markdown 结构块切片器（默认实现）"""

    def chunk(self, document: str) -> list[Chunk]:
        """按标题/代码块/表格/段落边界切分（代码块与表格为原子块）"""
        chunks: list[Chunk] = []
        order = 0
        heading = ""
        level = 0
        buffer: list[str] = []

        def flush() -> None:
            """将累积的正文段落写入切片（非空）"""
            nonlocal order, buffer
            text = "\n".join(buffer).strip()
            if text:
                chunks.append(Chunk(text=text, heading=heading, level=level, order=order))
                order += 1
            buffer = []

        def append_atomic(text: str) -> None:
            """写入原子块（代码块/表格）"""
            nonlocal order
            chunks.append(Chunk(text=text, heading=heading, level=level, order=order))
            order += 1

        lines = document.splitlines()
        i = 0
        in_code = False
        code_lines: list[str] = []
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # 代码块（原子块）
            if stripped.startswith("```"):
                if in_code:
                    in_code = False
                    append_atomic("\n".join(code_lines))
                    code_lines = []
                else:
                    flush()
                    in_code = True
                i += 1
                continue
            if in_code:
                code_lines.append(line)
                i += 1
                continue

            # 表格（原子块：| 行且后续存在分隔行）
            if _TABLE_ROW_RE.match(line) and self._is_table_block(lines, i):
                flush()
                table_lines: list[str] = []
                while i < len(lines) and _TABLE_ROW_RE.match(lines[i]):
                    table_lines.append(lines[i])
                    i += 1
                append_atomic("\n".join(table_lines))
                continue

            # 标题：刷新段落，更新上下文
            match = _HEADING_RE.match(stripped)
            if match:
                flush()
                heading = match.group(2).strip()
                level = len(match.group(1))
                i += 1
                continue

            # 正文：累积；空行不写入 buffer（作为段落分隔）
            if stripped:
                buffer.append(line)
            i += 1

        flush()
        return chunks

    @staticmethod
    def _is_table_block(lines: list[str], index: int) -> bool:
        """判断从 index 行起是否构成表格块（下一行是分隔行）"""
        if index + 1 >= len(lines):
            return False
        next_line = lines[index + 1].strip()
        # 分隔行包含 | 与 -，且不含纯文本
        return "|" in next_line and "-" in next_line and not _HEADING_RE.match(next_line)
