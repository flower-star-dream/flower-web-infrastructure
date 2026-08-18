"""
常量分类基础

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 定义常量分类前缀（PARAM_/AUTH_/INFRA_/BIZ_/SYS_）与通用常量，
              遵循规范 §5（常量分类统一管理）与 §6.9（AUTH_ 前缀常量）。
              业务域/模块常量应由各业务模块自行定义，禁止跨模块引用。
              常量值唯一权威来源为各分类常量类（ParamConstant/AuthConstant/InfraConstant/BizConstant/SysConstant），
              本模块仅重导出（兼容 from web_infra.infra.constants import X 的既有引用），禁止再定义重复常量。
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 常量分类前缀（规范 §5.3 分类维度）
# ---------------------------------------------------------------------------
PARAM_PREFIX = "PARAM_"      # 参数类：校验阈值、默认值、正则、分页
AUTH_PREFIX = "AUTH_"        # 权限类：角色码、权限点、凭证时效配置
INFRA_PREFIX = "INFRA_"      # 基础设施类：缓存 Key、消息 Topic、超时、重试
BIZ_PREFIX = "BIZ_"          # 业务域类：业务状态值、业务规则阈值
SYS_PREFIX = "SYS_"          # 系统类：框架配置、系统默认值、环境标识

# ---------------------------------------------------------------------------
# 分类常量类（规范 §5.3：按大类拆分常量类，常量值唯一权威来源）
# ---------------------------------------------------------------------------
from web_infra.infra.constants.auth_constant import AuthConstant
from web_infra.infra.constants.cache_key import CacheKeyBuilder
from web_infra.infra.constants.http_status_constant import HttpStatusConstant
from web_infra.infra.constants.infra_constant import InfraConstant
from web_infra.infra.constants.param_constant import ParamConstant
from web_infra.infra.constants.sys_constant import SysConstant
from web_infra.infra.constants.biz_constant import BizConstant

# ---------------------------------------------------------------------------
# 重导出（兼容既有 from web_infra.infra.constants import X 引用；值以分类常量类为准）
# ---------------------------------------------------------------------------

# 分页默认值（规范 §12.3：全局统一 pageNo/pageSize）
PARAM_COMMON_DEFAULT_PAGE_NO = ParamConstant.PARAM_COMMON_DEFAULT_PAGE_NO
PARAM_COMMON_DEFAULT_PAGE_SIZE = ParamConstant.PARAM_COMMON_DEFAULT_PAGE_SIZE
PARAM_COMMON_MAX_PAGE_SIZE = ParamConstant.PARAM_COMMON_MAX_PAGE_SIZE
# 深分页拒绝阈值（规范 §10.1：禁止 LIMIT offset 深分页，超阈值拒绝并建议游标分页）
PARAM_COMMON_MAX_OFFSET = ParamConstant.PARAM_COMMON_MAX_OFFSET

# 请求头常量（规范 §6.4 / §6.5 / §17.4；多租户扩展 §1.2 X-Tenant-Id）
AUTH_HEADER_AUTHORIZATION = AuthConstant.AUTH_HEADER_AUTHORIZATION
AUTH_HEADER_USER_ID = AuthConstant.AUTH_HEADER_USER_ID
AUTH_HEADER_SCOPE = AuthConstant.AUTH_HEADER_SCOPE
AUTH_HEADER_CLIENT_ID = AuthConstant.AUTH_HEADER_CLIENT_ID
AUTH_HEADER_SERVICE_ID = AuthConstant.AUTH_HEADER_SERVICE_ID
AUTH_HEADER_TRACE_ID = AuthConstant.AUTH_HEADER_TRACE_ID
AUTH_HEADER_TENANT_ID = AuthConstant.AUTH_HEADER_TENANT_ID
AUTH_HEADER_IDEMPOTENCY_KEY = AuthConstant.AUTH_HEADER_IDEMPOTENCY_KEY

# 认证凭证时效配置（规范 §6.9 / 附录 A.3；有效期统一为 AUTH_TOKEN_ACCESS_EXPIRE_MINUTES=120）
AUTH_TOKEN_ACCESS_EXPIRE_MINUTES = AuthConstant.AUTH_TOKEN_ACCESS_EXPIRE_MINUTES
AUTH_TOKEN_REFRESH_TTL_DAYS = AuthConstant.AUTH_TOKEN_REFRESH_TTL_DAYS
AUTH_TOKEN_BLACKLIST_PREFIX = AuthConstant.AUTH_TOKEN_BLACKLIST_PREFIX

# 权限范围（规范 §6.6）
AUTH_SCOPE_READ = AuthConstant.AUTH_SCOPE_READ
AUTH_SCOPE_WRITE = AuthConstant.AUTH_SCOPE_WRITE
AUTH_SCOPE_ADMIN = AuthConstant.AUTH_SCOPE_ADMIN

# 基础设施默认值（规范 §7 远程调用韧性）
INFRA_CALL_CONNECT_TIMEOUT_SECONDS = InfraConstant.INFRA_CALL_CONNECT_TIMEOUT_SECONDS  # 连接超时（规范 §7.1）
INFRA_CALL_MAX_RETRIES = InfraConstant.INFRA_CALL_MAX_RETRIES                          # 最大重试次数（规范 §7.2）
INFRA_CALL_RETRY_DELAY_BASE_SECONDS = InfraConstant.INFRA_CALL_RETRY_DELAY_BASE_SECONDS  # 重试退避初始延迟（秒）
INFRA_CALL_RETRY_DELAY_MAX_SECONDS = InfraConstant.INFRA_CALL_RETRY_DELAY_MAX_SECONDS    # 重试退避最大延迟（秒）
INFRA_CALL_RETRY_JITTER_MIN = InfraConstant.INFRA_CALL_RETRY_JITTER_MIN                  # 退避抖动下界
INFRA_CALL_RETRY_JITTER_MAX = InfraConstant.INFRA_CALL_RETRY_JITTER_MAX                  # 退避抖动上界
INFRA_LOCK_DEFAULT_TIMEOUT_SECONDS = InfraConstant.INFRA_LOCK_DEFAULT_TIMEOUT_SECONDS  # 锁获取超时（规范 §16.4）

# 数据库会话初始化命令：强制连接会话时区为 UTC（规范 §16.1 全链路 UTC）
INFRA_MYSQL_INIT_COMMAND = InfraConstant.INFRA_MYSQL_INIT_COMMAND

# 布尔真值集合（用于解析 JDBC/URL 风格参数）
INFRA_TRUE_VALUES = InfraConstant.INFRA_TRUE_VALUES

# 缓存 Key 前缀模板（规范 §5.7：web:{module}:v1:{biz}，占位符见 §5.6）
INFRA_CACHE_KEY_PATTERN = InfraConstant.INFRA_CACHE_KEY_PATTERN

# 分隔符约定（规范 §5.6：默认用 : 分隔段，段内用 _）
KEY_SEGMENT_SEPARATOR = InfraConstant.KEY_SEGMENT_SEPARATOR
KEY_INNER_SEPARATOR = InfraConstant.KEY_INNER_SEPARATOR

# SSE 响应媒体类型（规范 §5.7：基础设施媒体类型归 InfraConstant）
INFRA_SSE_MEDIA_TYPE = InfraConstant.INFRA_SSE_MEDIA_TYPE

__all__ = [
    "PARAM_PREFIX",
    "AUTH_PREFIX",
    "INFRA_PREFIX",
    "BIZ_PREFIX",
    "SYS_PREFIX",
    "PARAM_COMMON_DEFAULT_PAGE_NO",
    "PARAM_COMMON_DEFAULT_PAGE_SIZE",
    "PARAM_COMMON_MAX_PAGE_SIZE",
    "PARAM_COMMON_MAX_OFFSET",
    "AUTH_HEADER_AUTHORIZATION",
    "AUTH_HEADER_USER_ID",
    "AUTH_HEADER_SCOPE",
    "AUTH_HEADER_CLIENT_ID",
    "AUTH_HEADER_SERVICE_ID",
    "AUTH_HEADER_TRACE_ID",
    "AUTH_HEADER_TENANT_ID",
    "AUTH_HEADER_IDEMPOTENCY_KEY",
    "AUTH_TOKEN_ACCESS_EXPIRE_MINUTES",
    "AUTH_TOKEN_REFRESH_TTL_DAYS",
    "AUTH_TOKEN_BLACKLIST_PREFIX",
    "AUTH_SCOPE_READ",
    "AUTH_SCOPE_WRITE",
    "AUTH_SCOPE_ADMIN",
    "INFRA_CALL_CONNECT_TIMEOUT_SECONDS",
    "INFRA_CALL_MAX_RETRIES",
    "INFRA_CALL_RETRY_DELAY_BASE_SECONDS",
    "INFRA_CALL_RETRY_DELAY_MAX_SECONDS",
    "INFRA_CALL_RETRY_JITTER_MIN",
    "INFRA_CALL_RETRY_JITTER_MAX",
    "INFRA_LOCK_DEFAULT_TIMEOUT_SECONDS",
    "INFRA_MYSQL_INIT_COMMAND",
    "INFRA_TRUE_VALUES",
    "INFRA_CACHE_KEY_PATTERN",
    "KEY_SEGMENT_SEPARATOR",
    "KEY_INNER_SEPARATOR",
    "INFRA_SSE_MEDIA_TYPE",
    "AuthConstant",
    "CacheKeyBuilder",
    "HttpStatusConstant",
    "InfraConstant",
    "ParamConstant",
    "SysConstant",
    "BizConstant",
]
