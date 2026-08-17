"""
HTTP 客户端模块

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 声明式服务间 HTTP 客户端（Feign 风格）：服务发现 + 负载均衡 + 重试 + 熔断降级，
              并提供框架默认降级兜底（default_service_fallback）与 SSRF 地址校验器（default_url_validator）。
              build_feign_client 提供配置驱动的装配入口（app.feign 段，规范 §7）。
"""
from web_infra.http.feign_client import FeignClient, default_service_fallback
from web_infra.http.feign_client_factory import FeignClientConfig, build_feign_client

__all__ = [
    "FeignClient",
    "default_service_fallback",
    "FeignClientConfig",
    "build_feign_client",
]
