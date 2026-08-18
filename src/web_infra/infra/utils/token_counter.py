"""
Token 用量计算

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 按模型编码匹配本地 tokenizer 精确计算 token 用量，未匹配时回退字符数估算。
              tokenizer 加载成本高，采用单例 + 懒加载 + 有界 LRU 缓存保证并发安全与内存有界
              （规范 §16.4）；transformers 延迟导入。
"""
from __future__ import annotations

import logging
import os
import threading
from functools import lru_cache
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from transformers import PreTrainedTokenizerFast  # type: ignore[reportMissingImports]  # 可选依赖（extras[rag]）

logger = logging.getLogger(__name__)

# 中/英混合文本粗略估算：1 token ≈ 1.3 字符
_CHARS_PER_TOKEN_ESTIMATE = 1.3

# tokenizer 资源根目录，可通过环境变量 LLM_MODEL_RESOURCE_DIR 覆盖
_MODEL_RESOURCE_DIR = os.environ.get("LLM_MODEL_RESOURCE_DIR", "")


def _load_tokenizer_from_disk(model_dir: str) -> Optional["PreTrainedTokenizerFast"]:
    """从磁盘加载 tokenizer（不缓存，由调用方负责缓存）；transformers 延迟导入。

    加载失败返回 None（调用方降级为字符估算），并记录 warning 日志。
    """
    try:
        from transformers import AutoTokenizer  # type: ignore[reportMissingImports]  # 可选依赖（extras[rag]）

        return AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("tokenizer_load_failed model_dir=%s error=%s", model_dir, str(e))
        return None


@lru_cache(maxsize=4)
def _load_tokenizer_impl(model_dir: str) -> Optional["PreTrainedTokenizerFast"]:
    """加载并缓存 tokenizer（有界 LRU：最多缓存 4 个，防止内存无界增长，规范 §16.4）。

    lru_cache 线程安全（内部持有锁），缓存键为 tokenizer 目录名；
    同名 model_dir 多次调用返回同一 tokenizer 实例。
    """
    return _load_tokenizer_from_disk(model_dir)


class TokenCounter:
    """Token 用量计算器（单例）：按 model_code 匹配 tokenizer 精确计数，否则字符估算"""

    _instance: Optional["TokenCounter"] = None
    # S16-2 豁免：临界区为纯内存操作，无 I/O 阻塞，不适用 3s 获取超时
    _instance_lock = threading.Lock()
    # S16-4：tokenizer 静态缓存已改为有界 LRU（lru_cache maxsize=4，见 _load_tokenizer_impl），
    # 不再使用无界 dict 缓存；lru_cache 内部自带锁，无需额外加载锁。
    # model_code 前缀 -> tokenizer 目录名，业务可注册自定义映射
    _tokenizer_dirs: dict[str, str] = {}

    def __new__(cls) -> "TokenCounter":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def register_tokenizer(cls, prefix: str, dir_name: str) -> None:
        """注册模型编码前缀与 tokenizer 目录的映射"""
        cls._tokenizer_dirs[prefix.lower()] = dir_name

    @classmethod
    def get_instance(cls) -> "TokenCounter":
        """获取单例实例"""
        return cls()

    def count_tokens(self, text: str, model_code: str | None = None) -> int:
        """计算文本 token 用量；命中 tokenizer 为精确计数，否则字符估算"""
        if not text:
            return 0
        model_dir = self._resolve_tokenizer_dir(model_code or "")
        if model_dir is not None:
            tokenizer = self._load_tokenizer(model_dir)
            if tokenizer is not None:
                return len(tokenizer.encode(text, add_special_tokens=False))
        return max(1, int(len(text) / _CHARS_PER_TOKEN_ESTIMATE))

    def _resolve_tokenizer_dir(self, model_code: str) -> Optional[str]:
        """按 model_code 最长前缀匹配 tokenizer 目录"""
        lower = model_code.lower()
        matched: str | None = None
        for prefix in self._tokenizer_dirs:
            if lower.startswith(prefix) and (matched is None or len(prefix) > len(matched)):
                matched = prefix
        if matched is None or not _MODEL_RESOURCE_DIR:
            return None
        return os.path.join(_MODEL_RESOURCE_DIR, self._tokenizer_dirs[matched])

    def _load_tokenizer(self, model_dir: str) -> Optional["PreTrainedTokenizerFast"]:
        """加载并缓存 tokenizer；失败返回 None（降级字符估算）。

        S16-4：tokenizer 静态缓存为有界 LRU（maxsize=4，见 _load_tokenizer_impl），
        不再使用无界 dict 缓存，防止内存无界增长；同名目录返回同一实例。
        """
        return _load_tokenizer_impl(model_dir)


def count_tokens(text: str, model_code: str | None = None) -> int:
    """计算文本 token 用量的便捷函数"""
    return TokenCounter.get_instance().count_tokens(text, model_code)
