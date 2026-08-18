"""
认证域常量（AUTH_ 前缀）

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 认证/权限相关常量（JWT 算法、Token 有效期、Bearer 标识、请求头、权限范围等），对应错误码大类 E2。
              AUTH_ 前缀常量唯一权威来源（规范 §6.9），constants/__init__.py 重导出保持一致。
              注：凭证实际有效期统一为 AUTH_TOKEN_ACCESS_EXPIRE_MINUTES=120（走 SecureConfigLoader 默认值），
              历史 AUTH_TOKEN_ACCESS_TTL_MINUTES=15 无使用方且与生效值冲突，已移除。
"""
from __future__ import annotations


class AuthConstant:
    """认证域常量类（规范 §5.2 / §5.3）"""

    # JWT 配置
    AUTH_JWT_ALGORITHM = "HS256"
    AUTH_JWT_ISSUER = "web-infra"
    AUTH_TOKEN_ACCESS_EXPIRE_MINUTES = 120
    AUTH_TOKEN_REFRESH_TTL_DAYS = 7
    AUTH_TOKEN_BLACKLIST_PREFIX = "auth:bl:"
    AUTH_TOKEN_BEARER = "Bearer"
    AUTH_TOKEN_BEARER_PREFIX = "Bearer "
    AUTH_PASSWORD_BCRYPT_MAX_BYTES = 72

    # 请求头常量（规范 §6.4 / §6.5 / §17.4；多租户扩展 §1.2 X-Tenant-Id）
    AUTH_HEADER_AUTHORIZATION = "Authorization"
    AUTH_HEADER_USER_ID = "X-User-Id"
    AUTH_HEADER_SCOPE = "X-Scope"
    AUTH_HEADER_CLIENT_ID = "X-Client-Id"
    AUTH_HEADER_SERVICE_ID = "X-Service-Id"
    AUTH_HEADER_TRACE_ID = "X-Trace-Id"
    AUTH_HEADER_TENANT_ID = "X-Tenant-Id"
    AUTH_HEADER_IDEMPOTENCY_KEY = "Idempotency-Key"

    # 权限范围 Scope（规范 §6.6：凭证中的权限范围，常量前缀 AUTH_SCOPE_）
    AUTH_SCOPE_READ = "read"
    AUTH_SCOPE_WRITE = "write"
    AUTH_SCOPE_ADMIN = "admin"  # 超级管理员（通配所有权限点）

    # 资源权限点（规范 §6.6：声明式控制，常量前缀 AUTH_PERM_，禁止裸字符串）
    AUTH_PERM_ORDER_READ = "ORDER_READ"
    AUTH_PERM_ORDER_WRITE = "ORDER_WRITE"
