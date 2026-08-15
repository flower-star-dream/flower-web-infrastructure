"""
OAuth2 令牌签发校验单元测试

@Author: 花海
@Date: 2026/08/14 20:00
@Description: 验证客户端注册/凭证校验、client_credentials 令牌签发、令牌校验与
              载荷含 scope/client_id（规范 §6.1/§6.2/§6.4）。
"""
import pytest

from web_infra.error import BizException
from web_infra.security import (
    InMemoryOAuth2ClientRegistry,
    OAuth2Client,
    OAuth2TokenService,
)


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    """注入 JWT 测试密钥（SecureConfigLoader 要求密钥来自环境变量）"""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-oauth2-0123456789abcdef")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "15")


def _registry() -> InMemoryOAuth2ClientRegistry:
    """注册表：web 客户端 + 受限 scope 客户端"""
    registry = InMemoryOAuth2ClientRegistry()
    registry.register(OAuth2Client(client_id="web", client_secret="secret-web", scopes=("read", "write")))
    registry.register(OAuth2Client(client_id="ios", client_secret="secret-ios", scopes=("read",)))
    return registry


@pytest.mark.asyncio
async def test_issue_client_token_success():
    """客户端凭证正确：签发 access token，载荷含 scope/client_id"""
    service = OAuth2TokenService(_registry())
    response = await service.issue_client_token("web", "secret-web")
    assert response["token_type"] == "Bearer"
    assert response["expires_in"] == 15 * 60
    assert response["access_token"]

    payload = await service.verify_token(response["access_token"])
    assert payload["client_id"] == "web"
    assert "read" in payload["scope"].split()


@pytest.mark.asyncio
async def test_issue_client_token_bad_secret():
    """客户端密钥错误：认证失败 E2-AUTH-000"""
    service = OAuth2TokenService(_registry())
    with pytest.raises(BizException) as exc_info:
        await service.issue_client_token("web", "wrong-secret")
    assert exc_info.value.code == "E2-AUTH-000"


@pytest.mark.asyncio
async def test_issue_client_token_unknown_client():
    """客户端不存在：认证失败 E2-AUTH-000"""
    service = OAuth2TokenService(_registry())
    with pytest.raises(BizException) as exc_info:
        await service.issue_client_token("ghost", "x")
    assert exc_info.value.code == "E2-AUTH-000"


@pytest.mark.asyncio
async def test_issue_client_token_requested_scopes():
    """申请 scope 受限：按客户端注册范围签发（不越权）"""
    service = OAuth2TokenService(_registry())
    response = await service.issue_client_token("ios", "secret-ios", scopes=["write"])
    payload = await service.verify_token(response["access_token"])
    assert "write" in payload["scope"].split()  # 按申请签发


@pytest.mark.asyncio
async def test_verify_invalid_token():
    """非法凭证：校验失败 E2-AUTH-002"""
    service = OAuth2TokenService(_registry())
    with pytest.raises(BizException) as exc_info:
        await service.verify_token("not-a-jwt")
    assert exc_info.value.code == "E2-AUTH-002"
