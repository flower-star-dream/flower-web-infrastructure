"""客户端真实 IP 解析模块

@Author: 花海
@Date: 2026/08/18
@Description: 从 HTTP 请求中解析客户端真实 IP，供请求日志、登录失败 IP 锁定等场景复用
"""
from fastapi import Request

from web_infra.infra.utils.ip_address_util import IPAddressUtil


def get_client_ip(request: Request) -> str | None:
    """
    获取客户端真实 IP

    前端经 Nginx/OpenResty 反向代理转发，代理层（1Panel OpenResty）配置：
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    因此设计如下（防止绕过代理直连后端后伪造代理头）：
      1. 仅当直连方（request.client.host）为可信代理时（见 IPAddressUtil.is_trusted_proxy，
         默认可信代理为回环 + 私网段，覆盖容器网络内的 OpenResty/APISIX），才信任代理头；
      2. 可信代理透传时优先 X-Real-IP：代理用 $remote_addr 覆盖设置，客户端无法伪造，最可信；
      3. 其次 X-Forwarded-For 最后一项：$proxy_add_x_forwarded_for 在末尾追加 $remote_addr
         （直连代理的真实客户端 IP），取最后一项可避开客户端伪造的前缀；
      4. 直连方不可信（如公网攻击者绕过代理直连后端 8080）时，忽略一切代理头，
         以直连方地址作为客户端 IP，使伪造 X-Real-IP / XFF 绕过或封禁任意 IP 的尝试失效。

    若最终识别出的客户端 IP 为私网/保留段（容器网络、内网 NAT 等），登录失败仅按用户名维度
    锁定、不进行 IP 维度锁定（见 AuthService），避免误封后端自身容器与 OpenResty 容器 IP。

    :param request: 当前请求
    :return: 客户端 IP；无法获取时返回 None
    """
    client_host = request.client.host if request.client else None
    # 仅直连方为可信代理时才读取代理头，否则视为直连方伪造，直接取直连方地址
    if client_host and IPAddressUtil.is_trusted_proxy(client_host):
        x_real_ip = request.headers.get("x-real-ip")
        if x_real_ip:
            return x_real_ip.strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            parts = [part.strip() for part in xff.split(",") if part.strip()]
            if parts:
                return parts[-1]
    return client_host


def apply_real_client_ip(request: Request, real_ip: str | None) -> None:
    """
    将真实客户端 IP 写回 request.scope["client"]，使 uvicorn 默认访问日志显示真实 IP。

    uvicorn 的 access log（`INFO: 172.18.0.1:43750 - "GET ..." 200 OK`）在响应发送完成后
    通过 `get_client_addr(scope)` 实时读取 `scope["client"]`（即 TCP 连接对端，容器场景下为
    OpenResty 代理容器 IP）。scope 与 ASGI 中间件链共享同一对象引用，因此在此处改写后，
    uvicorn 打印 access log 时读到的即为真实客户端 IP（保留原端口），
    同时所有后续基于 request.client / scope["client"] 的输出也保持一致。

    :param request: 当前请求
    :param real_ip: 已解析的真实客户端 IP（为空时不改写，保持直连方地址）
    """
    if not real_ip:
        return
    original_client = request.scope.get("client")
    # 仅当解析出的 IP 与直连方不同才改写；无法获取原直连方（client 为 None）时跳过
    if original_client and original_client[0] != real_ip:
        request.scope["client"] = (real_ip, original_client[1])
