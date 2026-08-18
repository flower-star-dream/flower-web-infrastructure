"""
支付配置单元测试

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 覆盖 PaymentConfig/WechatPayConfig 默认值、字段解析、from_settings 装配与校验。
"""
import pytest
from pydantic import ValidationError

from web_infra.infra.config.dict_config_source import DictConfigSource
from web_infra.infra.config.settings import Settings
from web_infra.capabilities.payment.payment_config import PaymentConfig, WechatPayConfig


def test_wechat_config_defaults():
    """WechatPayConfig：默认值（verify_mode=platform_cert，超时默认）"""
    cfg = WechatPayConfig()
    assert cfg.verify_mode == "platform_cert"
    assert cfg.connect_timeout == 5.0
    assert cfg.read_timeout == 30.0
    assert cfg.appid == ""


def test_wechat_config_invalid_verify_mode():
    """WechatPayConfig：非法 verify_mode 触发 ValidationError"""
    with pytest.raises(ValidationError):
        WechatPayConfig(verify_mode="rsa_cert")


def test_payment_config_default_type():
    """PaymentConfig：默认渠道类型 memory"""
    cfg = PaymentConfig()
    assert cfg.type == "memory"
    assert isinstance(cfg.wechat, WechatPayConfig)


def test_payment_config_from_settings():
    """PaymentConfig.from_settings：从 Settings 读取 app.payment 装配"""
    settings = Settings(DictConfigSource({
        "app.payment": {
            "type": "wechat",
            "wechat": {"appid": "wx-test", "mchid": "1900000001", "verify_mode": "public_key"},
        }
    }))
    cfg = PaymentConfig.from_settings(settings)
    assert cfg.type == "wechat"
    assert cfg.wechat.appid == "wx-test"
    assert cfg.wechat.verify_mode == "public_key"


def test_payment_config_from_settings_empty():
    """PaymentConfig.from_settings：无 app.payment 配置时回落默认值"""
    settings = Settings(DictConfigSource({}))
    cfg = PaymentConfig.from_settings(settings)
    assert cfg.type == "memory"
