"""
模型配置管理

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 标准化模型配置视图（AI 规范 §2/§3）。
              安全说明（规范 AI-7）：API Key 禁止明文落盘——生产环境 api_key 字段应使用
              ``env:ENV_VAR_NAME`` 环境变量引用语法或配置中心加密存储；
              密钥按 ≥90 天周期轮换（与网关鉴权 kid 机制配合，密钥版本轮换不中断服务）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

#: API Key 环境变量引用前缀（``env:ENV_VAR_NAME``，规范 AI-7）
_ENV_REF_PREFIX = "env:"


@dataclass(frozen=True)
class ModelConfig:
    """标准化模型配置视图

    安全说明（规范 AI-7）：api_key 字段禁止明文落盘——
    生产环境应使用 ``env:ENV_VAR_NAME`` 环境变量引用语法（如 ``env:LLM_API_KEY``）
    或配置中心加密存储；密钥按 ≥90 天周期轮换（与网关鉴权 kid 机制配合，密钥版本轮换不中断服务）。
    """

    id: int
    model_name: str
    model_code: str
    provider: str
    api_base: str
    api_key: str
    model_id: str | None = None  # 厂商侧真实模型 ID（如 deepseek-chat）；缺省使用 model_code
    max_tokens: int = 4096
    temperature: float = 0.0
    top_p: float = 0.0
    timeout: int = 120
    is_deterministic: bool = False
    stop: str | list[str] | None = None
    input_price_per_1k: float = 0.0   # 输入 Token 单价（元 / 1K tokens，AI 规范 §5.2 成本计量）
    output_price_per_1k: float = 0.0  # 输出 Token 单价（元 / 1K tokens）

    @property
    def resolved_api_key(self) -> str:
        """解析后的 API Key（只读）：支持 ``env:ENV_VAR_NAME`` 环境变量引用语法。

        api_key 值以 ``env:`` 前缀开头时，从 os.environ 读取对应环境变量（规范 AI-7：
        API Key 通过环境变量/配置中心注入，禁止明文落盘）；
        环境变量缺失时原样返回原值（便于排查配置错误），不抛异常。
        """
        raw = self.api_key
        if raw.startswith(_ENV_REF_PREFIX):
            env_name = raw[len(_ENV_REF_PREFIX):]
            if env_name in os.environ:
                return os.environ[env_name]
        return raw

    def get_api_key(self) -> str:
        """获取解析后的 API Key（与 resolved_api_key 等价，方法形式便于显式调用）。"""
        return self.resolved_api_key

    def to_call_kwargs(self, *, deterministic: bool = True) -> dict[str, Any]:
        """转换为模型调用参数（可选参数为 None 时不传；api_key 使用解析后的值）"""
        temperature = 0.0 if (deterministic and self.is_deterministic) else self.temperature
        top_p = self.top_p if self.top_p and self.top_p > 0 else 0.01
        kwargs: dict[str, Any] = {
            "model": self.model_code,
            "api_key": self.resolved_api_key,
            "base_url": self.api_base,
            "timeout": self.timeout,
            "temperature": temperature,
            "top_p": top_p,
        }
        if self.stop is not None:
            kwargs["stop"] = self.stop
        return kwargs
