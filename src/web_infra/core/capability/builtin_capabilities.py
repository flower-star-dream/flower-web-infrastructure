"""
内置能力注册

@Author: 花海
@Date: 2026/08/17 16:00
@Description: 框架内置能力契约（全能力依赖图）：核心依赖链 用户系统(user，契约能力，业务实现)
              → 认证(authn，web_infra.capabilities.security) → 鉴权(authz，web_infra.capabilities.security) → 支付(pay，web_infra.capabilities.payment)；
              认证与鉴权一样依赖用户系统才有意义（"你是谁"→"你能做什么"→"你付钱"）；其余能力
              （AI/MQ/对象存储/注册发现/配置/数据访问/缓存）按各自框架模块登记，需明确依赖时声明。
              业务层可经 CapabilityRegistry 扩展注册自定义能力（如订单能力依赖支付）。
"""
from __future__ import annotations

from web_infra.core.capability.capability import Capability
from web_infra.core.capability.capability_registry import CapabilityRegistry

BUILTIN_CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        name="user",
        description="用户系统（契约能力：框架仅声明依赖与接入点，具体实现由业务层提供，如脚手架 user-service）",
        contract="用户身份与账号域能力：注册/登录/资料/绑定；框架侧接入点：RequestContext 身份上下文、"
                 "SocialBindingStore（三方绑定）、OAuth2Client（授权）",
    ),
    Capability(
        name="authn",
        description="认证：确认『你是谁』——JWT 签发/校验、Token 存储、三方登录、OAuth2 登录（web_infra.capabilities.security）",
        modules=("web_infra.capabilities.security",),
        requires=("user",),
        contract="认证前置用户系统（无用户则认证无意义）；框架 SPI 开箱即用：JwtKeyProvider / JwtTokenStore / "
                 "AuthMiddleware（登录签发/校验）",
    ),
    Capability(
        name="authz",
        description="鉴权：确认『你能做什么』——权限守卫/RBAC（web_infra.capabilities.security，PermissionGuard）",
        modules=("web_infra.capabilities.security",),
        requires=("authn",),
        contract="鉴权前置认证（先认证身份，再按角色/权限点校验）；框架 SPI：PermissionGuard 声明式权限控制",
    ),
    Capability(
        name="pay",
        description="支付：渠道 SPI + 回调验签/分发 + 骨架兜底 + 超时关单/对账/冲正/风控（web_infra.capabilities.payment）",
        modules=("web_infra.capabilities.payment",),
        requires=("authz",),
        contract="支付前置鉴权（确认付款人有权限），传递依赖认证/用户系统；框架 SPI：PaymentGateway / "
                 "PaymentCallbackVerifier / PaymentCallbackHandler；渠道实现（如微信 WeChatPayProvider）由业务层按契约接入",
    ),
    Capability(
        name="ai",
        description="AI 模型网关：供应商/模型路由/配额/检索/内容安全/缓存（web_infra.capabilities.ai）",
        modules=("web_infra.capabilities.ai",),
        contract="框架 SPI：ModelProviderInterface / ModelGateway / Retrieval / ContentGuard，业务层配置模型与策略",
    ),
    Capability(
        name="mq",
        description="消息队列：发布/幂等消费/事务发件箱/死信（web_infra.capabilities.mq）",
        modules=("web_infra.capabilities.mq",),
    ),
    Capability(
        name="storage",
        description="对象存储与分片上传（web_infra.capabilities.storage）",
        modules=("web_infra.capabilities.storage",),
    ),
    Capability(
        name="registry",
        description="服务注册发现：Nacos / 内存注册表 + 负载均衡（web_infra.capabilities.registry）",
        modules=("web_infra.capabilities.registry",),
    ),
    Capability(
        name="config",
        description="配置：本地 YAML/环境/字典源 + Nacos 配置中心（web_infra.infra.config）",
        modules=("web_infra.infra.config",),
    ),
    Capability(
        name="db",
        description="数据访问：ORM 会话/读写分离/多租户过滤/分页（web_infra.capabilities.db）",
        modules=("web_infra.capabilities.db",),
    ),
    Capability(
        name="cache",
        description="缓存：内存/Redis 后端 + 键构建（web_infra.capabilities.cache）",
        modules=("web_infra.capabilities.cache",),
    ),
    Capability(
        name="search",
        description="搜索引擎：全文检索 SPI + 内存默认实现 + ES 生产实现（web_infra.capabilities.search；"
                    "向量检索经 ElasticsearchVectorStore 接入 VectorStoreInterface，dense_vector + kNN）",
        modules=("web_infra.capabilities.search",),
        contract="框架 SPI：SearchEngineInterface（索引生命周期/写入/删除/关键词检索，全文 BM25/高亮）；"
                 "默认 memory 无外部依赖，生产注入 elasticsearch-dsl（es extra）",
    ),
)


def register_builtin_capabilities() -> None:
    """注册框架内置能力契约（幂等，可重复调用）。"""
    for capability in BUILTIN_CAPABILITIES:
        CapabilityRegistry.register(capability)
