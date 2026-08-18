"""
图形验证码服务单元测试

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 验证内存/Redis 存储的生成、一次性消费、TTL 过期与去混淆字符集。
"""
import time

import pytest

from web_infra.capabilities.security import CaptchaService, InMemoryCaptchaStore, RedisCaptchaStore


@pytest.mark.asyncio
async def test_generate_returns_id_and_code():
    """生成返回 captcha_id 与验证码，验证码来自去混淆字符池"""
    service = CaptchaService()
    captcha_id, code = await service.generate(length=4)
    assert captcha_id
    assert len(code) == 4
    # 去混淆：不含 0/O/1/l/I
    for ch in code:
        assert ch not in "0O1lI"


@pytest.mark.asyncio
async def test_verify_success_once():
    """校验成功且一次性消费：首次通过、再次失败"""
    service = CaptchaService()
    captcha_id, code = await service.generate()
    assert await service.verify(captcha_id, code) is True
    assert await service.verify(captcha_id, code) is False


@pytest.mark.asyncio
async def test_verify_case_insensitive():
    """大小写不敏感校验"""
    service = CaptchaService()
    captcha_id, code = await service.generate()
    assert await service.verify(captcha_id, code.lower()) is True


@pytest.mark.asyncio
async def test_verify_wrong_code_fails():
    """错误验证码校验失败（且原验证码被消费）"""
    service = CaptchaService()
    captcha_id, _ = await service.generate()
    assert await service.verify(captcha_id, "XXXX") is False
    # 错误码也会被取走，避免无限重试
    assert await service.verify(captcha_id, "XXXX") is False


@pytest.mark.asyncio
async def test_verify_empty_input_fails():
    """空 captcha_id 或空 code 直接失败"""
    service = CaptchaService()
    captcha_id, code = await service.generate()
    assert await service.verify("", code) is False
    assert await service.verify(captcha_id, "") is False


@pytest.mark.asyncio
async def test_ttl_expiry_memory_store():
    """内存存储：TTL 过期后校验失败"""
    service = CaptchaService(store=InMemoryCaptchaStore())
    captcha_id, code = await service.generate(ttl_seconds=1)
    # 模拟时间流逝：直接操作存储内部
    now = time.monotonic()
    store = service.store  # type: ignore[union-attr]
    assert isinstance(store, InMemoryCaptchaStore)
    for cid in list(store._store):
        stored_code, _ = store._store[cid]
        store._store[cid] = (stored_code, now - 1)  # 过期
    assert await service.verify(captcha_id, code) is False


class _FakeRedisGetdel:
    """模拟 redis.asyncio 的 set(ex)/getdel 语义"""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttl: dict[str, float] = {}
        self._now: float = 0.0

    def advance(self, seconds: float) -> None:
        self._now += seconds

    def _purge(self, key: str) -> None:
        expire_at = self._ttl.get(key)
        if expire_at is not None and expire_at <= self._now:
            self._store.pop(key, None)
            self._ttl.pop(key, None)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value
        if ex is not None:
            self._ttl[key] = self._now + ex

    async def getdel(self, key: str) -> str | None:
        self._purge(key)
        return self._store.pop(key, None)


@pytest.mark.asyncio
async def test_redis_store_once_and_expire():
    """Redis 存储：一次性消费 + TTL 过期"""
    fake = _FakeRedisGetdel()
    service = CaptchaService(store=RedisCaptchaStore(fake))
    captcha_id, code = await service.generate(ttl_seconds=10)
    assert await service.verify(captcha_id, code) is True
    assert await service.verify(captcha_id, code) is False

    captcha_id2, code2 = await service.generate(ttl_seconds=10)
    fake.advance(11)  # 超过 TTL
    assert await service.verify(captcha_id2, code2) is False
