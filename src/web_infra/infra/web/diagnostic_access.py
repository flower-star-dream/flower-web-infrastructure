"""
诊断端点访问守卫（生产 IP 白名单）

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 诊断端点访问守卫（设计文档《并发访问能力评估设计.md》§9）：/capacity 与
              /metrics 共用——生产环境（app_env=prod）默认仅允许内网来源（精确白名单
              5 段 + allowed_cidrs 追加），外部 IP 拒绝 403。安全语义与 IPAddressUtil
              的 is_private_or_reserved（登录防封禁，fail-open）**相反**：本守卫为鉴权
              场景，**fail-closed**——get_client_ip 返回 None（无法确定客户端身份）时
              拒绝，防解析异常被利用绕过白名单。IP 解析复用 IPAddressUtil._parse_ip
              （IPv4 映射 IPv6 自动转回 IPv4 判断）；网段命中复用 _in_any_network。
"""
from __future__ import annotations

import ipaddress
import logging
from typing import Callable

from fastapi import Request

from web_infra.infra.utils.ip_address_util import IPAddressUtil
from web_infra.infra.web.client_ip import get_client_ip

logger = logging.getLogger("web_infra.infra.web.diagnostic_access")

# 默认内网白名单（设计文档 §9：精确 5 段，IPv4 映射 IPv6 经 _parse_ip 转回 IPv4 判断）。
# 常量定义在守卫模块而非 capacity 模块：守卫由 Application 独立装配（_setup_diagnostic_guard，
# 不依赖 app.capacity.enabled），避免 infra 层反向依赖可延迟加载的 capabilities 包。
DEFAULT_ALLOWED_CIDRS = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
)


class DiagnosticAccessGuard:
    """诊断端点访问守卫：生产环境 IP 白名单（fail-closed）"""

    def __init__(
        self,
        enabled: bool = True,
        allowed_cidrs: tuple[str, ...] = (),
        *,
        is_production: Callable[[], bool] | None = None,
    ) -> None:
        """初始化守卫。

        :param enabled: 是否启用白名单（app.diagnostics.access.enabled；非生产环境实际
            不生效——生效条件还需 app_env==prod，见 _check）
        :param allowed_cidrs: 追加白名单 CIDR（默认精确 5 段由 effective_cidrs 提供）
        :param is_production: 生产环境判定回调（默认读 Settings.is_production，
            便于测试注入固定值）
        """
        self._enabled = enabled
        self._allowed_cidrs = allowed_cidrs
        self._is_production = is_production or self._default_is_production
        # 预解析为网段对象（构造期校验 CIDR 合法性，非法配置快速失败而非运行时才暴露）
        self._networks = tuple(ipaddress.ip_network(cidr, strict=False) for cidr in self.effective_cidrs())

    @property
    def allowed_cidrs(self) -> tuple[str, ...]:
        """追加白名单 CIDR（配置原样返回）"""
        return self._allowed_cidrs

    def effective_cidrs(self) -> tuple[str, ...]:
        """生效白名单 = 默认精确 5 段 + 追加 CIDR（去重保序，与配置模型一致）。

        默认 5 段（§9）：127.0.0.1、::1、10/8、172.16/12、192.168/16。
        注意：与 IPAddressUtil 的私网全集（含 CGNAT/组播/保留段）不同，本守卫仅
        精确 5 段，避免把组播/保留段当可信来源放行。
        """
        merged = list(DEFAULT_ALLOWED_CIDRS)
        for cidr in self._allowed_cidrs:
            if cidr not in merged:
                merged.append(cidr)
        return tuple(merged)

    # ------------------------------------------------------------------
    # 对外判定
    # ------------------------------------------------------------------

    def check(self, request: Request) -> bool:
        """判定请求是否放行。

        :param request: 当前请求（经 get_client_ip 解析真实客户端 IP）
        :return: True 放行；False 拒绝（调用方返回 403）
        """
        if not self._enabled or not self._is_production():
            return True
        ip = get_client_ip(request)
        if ip is None:
            # fail-closed：无法确定客户端身份按不信任处理（§9）
            logger.warning("diagnostic_access_denied_no_ip path=%s", request.url.path)
            return False
        addr = IPAddressUtil._parse_ip(ip)
        if addr is None:
            # 无法解析的 IP 同样拒绝（与 is_private_or_reserved 的 fail-open 语义相反）
            logger.warning("diagnostic_access_denied_unparsable ip=%s", ip)
            return False
        if IPAddressUtil._in_any_network(addr, self._networks):
            return True
        logger.warning("diagnostic_access_denied ip=%s path=%s", ip, request.url.path)
        return False

    def __call__(self, request: Request) -> bool:
        """守卫实例可直接调用（委托 check，供端点以 Callable 参数注入）。

        装配路径将守卫实例传入 register_capacity_endpoints / register_health_endpoints
        的 access_guard 参数（Callable[[Request], bool]），端点内 `access_guard(request)`
        即调用本方法；未实现 __call__ 时实例不可调用会抛 TypeError（安全控制失效）。
        """
        return self.check(request)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    def _default_is_production() -> bool:
        """默认生产判定：读全局 Settings（app_env == prod）"""
        from web_infra.infra.config.settings import Settings

        return Settings.instance().is_production()
