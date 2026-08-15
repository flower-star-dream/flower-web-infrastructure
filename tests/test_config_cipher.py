"""
配置加密存储整改测试（S15-2）

@Author: 花海
@Date: 2026/08/15
@Description: 验证 ConfigCipher 加密/解密（enc:base64 密文，Fernet）：
              encrypt/decrypt 往返、无 enc: 前缀原样返回、密钥缺失降级、解密失败降级，
              以及 SecureConfigLoader 集成自动解密（规范 §15.2 敏感配置加密存储）。
"""
import pytest

from web_infra.config.config_cipher import ConfigCipher, ENV_ENCRYPT_KEY, ENCRYPTED_PREFIX
from web_infra.security.secure_config_loader import SecureConfigLoader


def _fresh_key() -> str:
    """生成一个新 Fernet 密钥（不依赖外部环境变量）"""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("utf-8")


# ------------------------------------------------------------------
# ConfigCipher 基础能力
# ------------------------------------------------------------------

def test_encrypt_decrypt_roundtrip():
    """encrypt -> decrypt 往返还原明文，密文带 enc: 前缀且不含明文"""
    cipher = ConfigCipher(key=_fresh_key())
    encrypted = cipher.encrypt("mysql-password-2026")
    assert encrypted.startswith(ENCRYPTED_PREFIX)
    assert "mysql-password-2026" not in encrypted
    assert cipher.decrypt(encrypted) == "mysql-password-2026"


def test_decrypt_plain_value_unchanged():
    """无 enc: 前缀的配置值原样返回（不尝试解密）"""
    cipher = ConfigCipher(key=_fresh_key())
    assert cipher.decrypt("plain-value") == "plain-value"
    assert cipher.decrypt("") == ""


def test_decrypt_without_key_degrades_to_original():
    """密钥缺失（无环境变量）：enc: 值告警并原样返回，不抛错（避免启动失败，规范 §15.2 降级）"""
    cipher = ConfigCipher(key="")
    encrypted = ConfigCipher(key=_fresh_key()).encrypt("secret")
    assert cipher.decrypt(encrypted) == encrypted  # 原样返回


def test_encrypt_without_key_raises():
    """密钥缺失时 encrypt 明确报错（防止产生无法解密的伪密文）"""
    cipher = ConfigCipher(key="")
    with pytest.raises(ValueError):
        cipher.encrypt("secret")


def test_decrypt_failed_with_wrong_key_degrades():
    """密钥错误/密文损坏：解密失败告警并原样返回，不抛错"""
    cipher = ConfigCipher(key=_fresh_key())
    wrong = ConfigCipher(key=_fresh_key())
    encrypted = wrong.encrypt("top-secret")
    assert cipher.decrypt(encrypted) == encrypted  # 密钥不匹配 -> 原样
    assert cipher.decrypt("enc:not-base64!") == "enc:not-base64!"  # 密文非法 -> 原样


def test_cipher_reads_key_from_env(monkeypatch):
    """key 缺省时从环境变量 CONFIG_ENCRYPT_KEY 读取"""
    key = _fresh_key()
    monkeypatch.setenv(ENV_ENCRYPT_KEY, key)
    cipher = ConfigCipher()
    assert cipher.decrypt(cipher.encrypt("from-env-key")) == "from-env-key"


# ------------------------------------------------------------------
# SecureConfigLoader 集成（自动解密 enc: 前缀配置值）
# ------------------------------------------------------------------

def test_loader_decrypts_encrypted_jwt_secret(monkeypatch):
    """JWT 密钥以 enc: 密文注入环境变量时自动解密（规范 §15.2）"""
    key = _fresh_key()
    monkeypatch.setenv(ENV_ENCRYPT_KEY, key)
    encrypted = ConfigCipher(key=key).encrypt("jwt-secret-abc")
    monkeypatch.setenv("JWT_SECRET_KEY", encrypted)

    assert SecureConfigLoader.get_jwt_secret() == "jwt-secret-abc"


def test_loader_plain_secret_unchanged(monkeypatch):
    """明文密钥（无 enc: 前缀）原样返回"""
    monkeypatch.delenv(ENV_ENCRYPT_KEY, raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "plain-jwt-secret")
    assert SecureConfigLoader.get_jwt_secret() == "plain-jwt-secret"


def test_loader_encrypted_expire_minutes(monkeypatch):
    """加密的 JWT_EXPIRE_MINUTES 解密后按 int 解析"""
    key = _fresh_key()
    monkeypatch.setenv(ENV_ENCRYPT_KEY, key)
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", ConfigCipher(key=key).encrypt("240"))
    assert SecureConfigLoader.get_jwt_expire_minutes() == 240


def test_loader_missing_key_degrades(monkeypatch):
    """密钥缺失时加密配置值原样返回（不抛错），明文密钥仍可用"""
    monkeypatch.delenv(ENV_ENCRYPT_KEY, raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "enc:whatever")
    assert SecureConfigLoader.get_jwt_secret() == "enc:whatever"
