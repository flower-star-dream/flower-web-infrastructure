"""
模型自动注册器

@Author: 花海
@Date: 2026/08/14 23:30
@Description: 模型自动注册器（AI 规范 §17.4/§3.2）：
              按模型配置清单（页面化配置/yml app.ai.models/ModelConfigStoreInterface）批量构建供应商，
              自动同步至 SPI 注册表，业务代码无需手动 register；
              同 model_code 重复配置时覆盖注册（配置刷新语义）。
              可选能力：fetch_remote_models 通过 OpenAI 兼容 /models 接口动态拉取模型列表
              （AI-10 页面化配置动态获取，网络调用仅在显式调用时发生，失败不阻断手动登记）。
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import fields
from typing import Any, Iterable

from web_infra.capabilities.ai.model_config import ModelConfig
from web_infra.capabilities.ai.model_config_store_interface import ModelConfigStoreInterface
from web_infra.capabilities.ai.model_provider_factory import ModelProviderFactory
from web_infra.capabilities.ai.model_provider_interface import ModelProviderInterface
from web_infra.capabilities.ai.model_provider_registry import ModelProviderRegistry
from web_infra.infra.constants import HttpStatusConstant

logger = logging.getLogger(__name__)


class ModelAutoRegistrar:
    """模型自动注册器：配置清单 -> 供应商实例 -> SPI 注册表"""

    def __init__(
        self,
        registry: type[ModelProviderRegistry] = ModelProviderRegistry,
        factory: type[ModelProviderFactory] = ModelProviderFactory,
    ) -> None:
        """初始化自动注册器。

        :param registry: 供应商注册表（默认类级注册表 ModelProviderRegistry）
        :param factory: 供应商协议构建器（默认 ModelProviderFactory）
        """
        self._registry = registry
        self._factory = factory
        self._created: list[ModelProviderInterface] = []

    async def register_from_store(self, store: ModelConfigStoreInterface) -> list[str]:
        """从模型配置来源 SPI 自动注册全部模型（页面化配置同步注册，AI 规范 §17.4）。

        :param store: 模型配置来源（数据库/配置中心实现）
        :return: 已注册的模型逻辑名列表
        """
        configs = await store.load_all()
        return self.register_configs(configs)

    def register_configs(self, configs: Iterable[ModelConfig]) -> list[str]:
        """按模型配置清单自动注册全部供应商（yml/内存配置同步注册）。

        :param configs: 模型配置清单
        :return: 已注册的模型逻辑名列表
        """
        registered: list[str] = []
        for config in configs:
            provider = self._factory.create(config)
            self._registry.register(provider)
            self._created.append(provider)
            registered.append(provider.name)
        return registered

    async def fetch_remote_models(self, provider_url: str, api_key: str, http_client: Any) -> list[str]:
        """调用 OpenAI 兼容供应商 ``GET {base_url}/models`` 接口动态拉取模型 ID 列表（AI-10 可选能力）。

        页面化配置「动态获取模型列表」依赖该接口（OpenAI 兼容协议的标准能力，规范 §17.4）；
        网络调用仅在显式调用本方法时发生，不影响手动登记流程（register_configs/register_from_store）；
        失败（网络异常/非 2xx/结构异常）时返回空列表并记录 warning 日志，不阻断手动登记流程。

        :param provider_url: 供应商 API 基地址（如 https://api.deepseek.com/v1）
        :param api_key: 供应商 API Key（应通过环境变量/配置中心注入，规范 AI-7，禁止明文落盘）
        :param http_client: httpx.AsyncClient 兼容的异步客户端（显式传入，便于测试注入 mock）
        :return: 模型 ID 列表（data[].id，过滤无 id 项）；失败返回空列表
        """
        url = f"{provider_url.rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            response = await http_client.get(url, headers=headers)
        except Exception as exc:  # 网络/超时等异常统一降级为空列表
            logger.warning("拉取远程模型列表失败（网络异常） url=%s err=%s", url, exc)
            return []
        if (
            getattr(response, "status_code", HttpStatusConstant.HTTP_OK)
            >= HttpStatusConstant.HTTP_CLIENT_ERROR_MIN
        ):
            logger.warning("拉取远程模型列表失败（非 2xx） url=%s status=%s", url, response.status_code)
            return []
        try:
            payload = response.json()
        except Exception as exc:  # JSON 解析失败降级为空列表
            logger.warning("拉取远程模型列表失败（响应解析异常） url=%s err=%s", url, exc)
            return []
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            logger.warning("远程模型列表响应结构异常（缺 data 数组） url=%s", url)
            return []
        model_ids: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id:
                model_ids.append(model_id)
        return model_ids

    async def close(self) -> None:
        """释放自动注册创建的供应商底层资源（应用停机时由生命周期自动调用）"""
        for provider in self._created:
            close = getattr(provider, "close", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
        self._created.clear()

    @staticmethod
    def from_dicts(items: list[dict] | None) -> list[ModelConfig]:
        """将 yml 配置清单（app.ai.models）转换为模型配置列表。

        仅保留 ModelConfig 字段（页面化配置可能携带其他展示字段）；
        缺省值：provider 未配置时回落 OpenAI 兼容协议（规范 §17.4 默认协议）。
        """
        valid_fields = {f.name for f in fields(ModelConfig)}
        configs: list[ModelConfig] = []
        for item in items or []:
            data = {key: value for key, value in item.items() if key in valid_fields}
            data.setdefault("provider", "openai_compatible")
            configs.append(ModelConfig(**data))
        return configs
