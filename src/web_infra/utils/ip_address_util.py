"""IP 地址工具类

@Author: 花海
@Date: 2026/08/18
@Description: 提供 IP 私网/保留段识别与可信代理判断，用于登录防暴力破解的 IP 维度锁定
"""
import ipaddress
import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)


class IPAddressUtil:
    """IP 地址工具类

    用途（登录防暴力破解 IP 维度锁定）：
    - 私网/保留/特殊 IP 段（含容器网络、内网 NAT、回环、链路本地、CGNAT 等）天然无法区分具体客户端，
      封禁会导致把后端自身容器、OpenResty/网关容器 IP 或内网共享出口误封，因此不参与 IP 维度锁定；
    - 可信代理判断：仅当请求直连方（request.client.host）为可信代理（OpenResty/APISIX 等）时，
      后端才信任其透传的 X-Real-IP / X-Forwarded-For 代理头，防止攻击者绕过代理直连后端后伪造代理头。
    """

    # 可信代理白名单环境变量：逗号分隔的 IP 或 CIDR 网段，用于追加默认白名单之外的代理
    # 默认可信代理为回环 + 私网段（OpenResty/APISIX/后端容器同处容器网络私网段，开箱即用）
    ENV_TRUSTED_PROXY_IPS = "TRUSTED_PROXY_IPS"

    # 私有/保留/特殊用途 IPv4 网段（含容器网络与内网 NAT，RFC1918 / RFC6890 / RFC6598 等）
    _PRIVATE_IPV4_NETWORKS = (
        ipaddress.ip_network("0.0.0.0/8"),        # "本网络"
        ipaddress.ip_network("10.0.0.0/8"),       # RFC1918 私网
        ipaddress.ip_network("100.64.0.0/10"),    # RFC6598 CGNAT 共享地址（运营商 NAT 后多用户共享）
        ipaddress.ip_network("127.0.0.0/8"),      # 回环
        ipaddress.ip_network("169.254.0.0/16"),   # 链路本地
        ipaddress.ip_network("172.16.0.0/12"),    # RFC1918 私网（含 Docker/容器网络 172.17-172.31）
        ipaddress.ip_network("192.0.0.0/24"),     # IETF 协议分配
        ipaddress.ip_network("192.0.2.0/24"),     # TEST-NET-1 文档示例
        ipaddress.ip_network("192.168.0.0/16"),   # RFC1918 私网
        ipaddress.ip_network("198.18.0.0/15"),    # 基准测试
        ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
        ipaddress.ip_network("203.0.113.0/24"),   # TEST-NET-3
        ipaddress.ip_network("224.0.0.0/4"),      # 组播
        ipaddress.ip_network("240.0.0.0/4"),      # 保留
        ipaddress.ip_network("255.255.255.255/32"),  # 广播
    )

    # 私有/保留/特殊用途 IPv6 网段
    _PRIVATE_IPV6_NETWORKS = (
        ipaddress.ip_network("::/128"),          # 未指定地址
        ipaddress.ip_network("::1/128"),         # 回环
        ipaddress.ip_network("fc00::/7"),        # RFC4193 ULA 私网
        ipaddress.ip_network("fe80::/10"),       # 链路本地
        ipaddress.ip_network("ff00::/8"),        # 组播
    )

    # 可信代理默认网段：回环 + 私网/保留段（OpenResty/APISIX 等容器网络 IP 均在此范围内）
    _TRUSTED_PROXY_NETWORKS = _PRIVATE_IPV4_NETWORKS + _PRIVATE_IPV6_NETWORKS

    @staticmethod
    def is_private_or_reserved(ip: str) -> bool:
        """
        判断 IP 是否属于私网/保留/特殊用途网段。

        用于登录失败 IP 维度锁定：返回 True 的 IP（容器网络、内网 NAT、回环、CGNAT 等）
        不参与失败计数与封禁，避免误封后端自身容器、OpenResty/网关容器或内网共享出口 IP。
        无法解析的非法 IP 也视为"不可封禁"（fail-open，保证可用性优先，绝不误封）。

        :param ip: 待判断的 IP 字符串（支持 IPv4 / IPv6 / IPv4 映射 IPv6）
        :return: True 表示私网/保留/特殊用途或无法解析，不应封禁；False 表示可区分公网客户端 IP
        """
        addr = IPAddressUtil._parse_ip(ip)
        if addr is None:
            # 非法 IP 视为不可封禁，防止异常数据触发误封
            logger.warning("unparsable_ip_treated_as_private", extra={"ip": ip})
            return True
        return IPAddressUtil._in_any_network(addr, IPAddressUtil._PRIVATE_IPV4_NETWORKS, IPAddressUtil._PRIVATE_IPV6_NETWORKS)

    @staticmethod
    def is_trusted_proxy(ip: str) -> bool:
        """
        判断请求直连方是否为可信反向代理（OpenResty/APISIX 等）。

        仅当直连方为可信代理时，后端才信任其透传的 X-Real-IP / X-Forwarded-For 代理头；
        否则忽略代理头、以直连方地址作为客户端 IP，防止攻击者绕过代理直连后端后伪造代理头
        实现绕过自身锁定或封禁任意 IP（DoS）。

        默认可信代理为回环 + 私网/保留段（与容器网络适配，开箱即用）；
        可通过环境变量 TRUSTED_PROXY_IPS（逗号分隔 IP/CIDR）追加额外白名单（如云负载均衡、多层代理）。

        :param ip: 待判断的直连方 IP
        :return: True 表示可信代理，其代理头可被信任；False 表示不可信直连方
        """
        addr = IPAddressUtil._parse_ip(ip)
        if addr is None:
            return False
        if IPAddressUtil._in_any_network(addr, IPAddressUtil._TRUSTED_PROXY_NETWORKS):
            return True
        for extra_network in IPAddressUtil._get_extra_trusted_proxy_networks():
            if addr in extra_network:
                return True
        return False

    @staticmethod
    def _parse_ip(ip: str) -> ipaddress._BaseAddress | None:
        """
        解析 IP 字符串为 ipaddress 地址对象；IPv4 映射 IPv6（::ffff:a.b.c.d）自动转换回 IPv4 判断。

        :param ip: IP 字符串
        :return: 地址对象；无法解析时返回 None
        """
        if not ip or not ip.strip():
            return None
        try:
            addr = ipaddress.ip_address(ip.strip())
        except ValueError:
            return None
        # IPv4 映射 IPv6 地址（如 ::ffff:1.2.3.4）转回 IPv4 参与网段判断
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            return addr.ipv4_mapped
        return addr

    @staticmethod
    def _in_any_network(addr: ipaddress._BaseAddress, *network_groups: tuple) -> bool:
        """
        判断地址是否命中任一网段组。

        :param addr: 地址对象
        :param network_groups: 一个或多个网段元组
        :return: 命中任一网段返回 True
        """
        for networks in network_groups:
            for network in networks:
                if addr in network:
                    return True
        return False

    @staticmethod
    @lru_cache(maxsize=None)
    def _get_extra_trusted_proxy_networks() -> tuple[ipaddress._BaseNetwork, ...]:
        """
        解析环境变量 TRUSTED_PROXY_IPS 为网段列表（逗号分隔 IP/CIDR），结果缓存。

        非法项忽略并记录告警，避免单个配置错误导致整段白名单失效。
        :return: 追加的可信代理网段元组
        """
        raw = os.getenv(IPAddressUtil.ENV_TRUSTED_PROXY_IPS, "")
        if not raw.strip():
            return ()
        networks = []
        for item in raw.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                networks.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                logger.warning("invalid_trusted_proxy_ip_ignored", extra={"value": item})
        return tuple(networks)

    @staticmethod
    def clear_trusted_proxy_cache() -> None:
        """清空可信代理白名单缓存，用于环境变量变化后强制刷新（测试用）。"""
        IPAddressUtil._get_extra_trusted_proxy_networks.cache_clear()
