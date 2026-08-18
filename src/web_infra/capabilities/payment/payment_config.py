"""
支付模块配置

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 支付模块配置模型（app.payment）：渠道类型与微信渠道参数。
              敏感配置经环境变量注入（$APP_PAYMENT_* 占位，见 application.default.yml）。
"""
from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field

from web_infra.infra.config.settings import Settings


class WechatPayConfig(BaseModel):
    """微信支付渠道配置（对齐 Java 侧 WeChatProperties）"""

    appid: str = Field(default="", description="微信小程序/公众号/App 应用 ID")
    mchid: str = Field(default="", description="微信支付商户号")
    mch_serial_no: str = Field(default="", description="商户 API 证书序列号（请求签名用）")
    api_v3_key: str = Field(default="", description="APIv3 密钥（回调报文 AES-256-GCM 解密）")
    private_key: str = Field(default="", description="商户 API 私钥 PEM 内容")
    private_key_path: str = Field(default="", description="商户 API 私钥 PEM 文件路径（与 private_key 二选一）")
    notify_url: str = Field(default="", description="支付成功回调地址")
    refund_notify_url: str = Field(default="", description="退款结果回调地址")
    verify_mode: Literal["platform_cert", "public_key"] = Field(default="platform_cert", description="回调验签凭据模式")
    platform_cert_dir: str = Field(default="./cert", description="微信支付平台证书 PEM 文件目录（文件名=<证书序列号>.pem）")
    cert_auto_download: bool = Field(default=False, description="平台证书自动下载（platform_cert 模式：验签遇未知序列号时自动调用 /v3/certificates 获取并缓存）")
    public_key_id: str = Field(default="", description="微信支付公钥 ID（public_key 模式）")
    public_key: str = Field(default="", description="微信支付公钥 PEM 内容（public_key 模式）")
    connect_timeout: float = Field(default=5.0, description="连接超时（秒）")
    read_timeout: float = Field(default=30.0, description="读超时（秒）")
    # 渠道调用失败兜底（默认开启，可配置关闭/调整）：
    # 支付接口 out_trade_no / out_refund_no 天然幂等，网络抖动 / 5xx / 429 可安全重试；
    # 4xx 业务错误（参数/状态冲突）不重试，由调用方按业务处理。
    retries: int = Field(default=2, description="渠道调用失败重试次数（可重试故障：网络/5xx/429；0 关闭重试）")
    retry_delay_base: float = Field(default=0.5, description="重试退避基数（秒），指数退避 base * 2^attempt")
    retry_delay_max: float = Field(default=4.0, description="重试退避上限（秒）")

    def load_verify_key(self, serial: str) -> str | None:
        """按证书序列号加载验签公钥 PEM：
        public_key 模式返回静态公钥；platform_cert 模式读取 <platform_cert_dir>/<serial>.pem。
        未找到返回 None（含并发清理竞态窗口的 FileNotFoundError 容错，H1 修复）。
        """
        if self.verify_mode == "public_key":
            return self.public_key or None
        cert_path = os.path.join(self.platform_cert_dir, f"{serial}.pem")
        try:
            with open(cert_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return None


class PaymentConfig(BaseModel):
    """支付模块配置（app.payment）"""

    type: str = Field(default="memory", description="默认渠道类型：memory | wechat")
    wechat: WechatPayConfig = Field(default_factory=WechatPayConfig, description="微信渠道配置")

    @classmethod
    def from_settings(cls, settings: Settings) -> "PaymentConfig":
        """从统一配置读取 app.payment 装配（缺省回落默认值）"""
        data = settings.get("app.payment") or {}
        return cls.model_validate(data)
