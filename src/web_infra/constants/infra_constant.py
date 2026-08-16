"""
基础设施域常量（INFRA_ 前缀）

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 基础设施相关常量（HTTP 超时、连接池、Nacos API 路径、健康状态、缓存 Key 模板等），对应错误码大类 E3。
              INFRA_ 前缀常量唯一权威来源，constants/__init__.py 重导出保持一致。
"""
from __future__ import annotations


class InfraConstant:
    """基础设施域常量类（规范 §5.2 / §5.3）"""

    # HTTP 客户端
    INFRA_HTTP_TIMEOUT_SECONDS = 30.0
    INFRA_HTTP_MAX_CONNECTIONS = 100
    INFRA_HTTP_MAX_KEEPALIVE_CONNECTIONS = 20

    # 远程调用韧性默认值（规范 §7.1 / §7.2）
    INFRA_CALL_CONNECT_TIMEOUT_SECONDS = 1       # 连接超时（规范 §7.1）
    INFRA_CALL_MAX_RETRIES = 2                   # 最大重试次数（规范 §7.2）
    # 指数退避参数（规范 §7.2：退避 = min(base * 2^attempt * jitter, max)）
    INFRA_CALL_RETRY_DELAY_BASE_SECONDS = 0.5    # 重试退避初始延迟（秒）
    INFRA_CALL_RETRY_DELAY_MAX_SECONDS = 8.0     # 重试退避最大延迟（秒）
    INFRA_CALL_RETRY_JITTER_MIN = 0.7            # 退避抖动下界（避免惊群）
    INFRA_CALL_RETRY_JITTER_MAX = 1.0            # 退避抖动上界

    # 分布式锁（规范 §16.4）
    INFRA_LOCK_DEFAULT_TIMEOUT_SECONDS = 3       # 锁获取超时

    # Nacos 客户端（服务注册对外 IP 探测；配置拉取/注册发现由官方 nacos-sdk-python v2 实现）
    INFRA_NACOS_PUBLIC_PROBE_HOST = "8.8.8.8"
    INFRA_NACOS_PUBLIC_PROBE_PORT = 80

    # MySQL（数据库会话初始化命令：强制连接会话时区为 UTC，规范 §16.1 全链路 UTC）
    INFRA_MYSQL_POOL_SIZE = 10
    INFRA_MYSQL_MAX_OVERFLOW = 5
    INFRA_MYSQL_INIT_COMMAND = "SET time_zone = '+00:00'"
    INFRA_TRUE_VALUES = ("true", "1", "yes", "on")

    # Redis
    INFRA_REDIS_TIMEOUT_SECONDS = 5
    INFRA_REDIS_HEALTH_CHECK_INTERVAL_SECONDS = 30

    # 健康检查状态
    INFRA_HEALTH_STATUS_UP = "UP"
    INFRA_HEALTH_STATUS_DOWN = "DOWN"

    # 默认数据源名
    INFRA_DEFAULT_DATASOURCE = "default"

    # 缓存 Key 前缀模板（规范 §5.7：web:{module}:v1:{biz}，占位符见 §5.6）
    INFRA_CACHE_KEY_PATTERN = "web:{module}:v1:{biz}"

    # 分隔符约定（规范 §5.6：默认用 : 分隔段，段内用 _）
    KEY_SEGMENT_SEPARATOR = ":"
    KEY_INNER_SEPARATOR = "_"

    # MQ（规范 §5.8：Topic/Tag/消费组命名，原 web_infra.mq.mq_constants 迁移至此统一管理）
    INFRA_MQ_TOPIC_ORDER = "web-order-topic"
    INFRA_MQ_TAG_ORDER_PAY = "ORDER_PAY"
    INFRA_MQ_GROUP_ORDER_PAY = "web-order-pay-consumer"

    # SSE（Server-Sent Events）响应媒体类型（规范 §5.7：基础设施媒体类型归 InfraConstant，
    # 原 BizConstant.BIZ_SSE_MEDIA_TYPE 迁移至此）
    INFRA_SSE_MEDIA_TYPE = "text/event-stream"
