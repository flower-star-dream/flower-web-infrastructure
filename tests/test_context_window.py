"""
上下文超长截断重试单元测试

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 验证错误解析、Token 预算截断与"解析 → 截断 → 重试"策略（AI 规范 §4.2/§4.3）。
"""
import pytest

from web_infra.ai import ContextWindowErrorParser, ContextTruncator, ContextWindowRetryPolicy


# ---------------------------------------------------------------------------
# 错误解析
# ---------------------------------------------------------------------------

def test_parse_requested_tokens():
    """解析 'you requested X tokens' 返回 X"""
    error = "This model's maximum context length is 128000 tokens. However you requested 128100 tokens."
    assert ContextWindowErrorParser.parse(error) == 128100


def test_parse_max_context_length():
    """仅含上下文上限时返回上限值"""
    error = "maximum context length is 4096 tokens, input too long"
    assert ContextWindowErrorParser.parse(error) == 4096


def test_parse_generic_exceeded_returns_zero():
    """仅命中通用超长提示返回 0（表示需截断但未知具体量）"""
    error = "The context window is too small, please shorten your input"
    assert ContextWindowErrorParser.parse(error) == 0


def test_parse_unrelated_error_returns_none():
    """无关错误返回 None（不应触发上下文超长重试）"""
    error = "rate limit exceeded, retry after 30s"
    assert ContextWindowErrorParser.parse(error) is None


# ---------------------------------------------------------------------------
# 截断
# ---------------------------------------------------------------------------

def test_truncate_within_budget_unchanged():
    """文本在预算内原样返回"""
    text = "短文本"
    assert ContextTruncator().truncate(text, budget_tokens=10000) == text


def test_truncate_over_budget_cuts_prefix():
    """超预算文本被截断（预算内），且截断后不超预算"""
    text = "这是用于测试截断的中文长文本，" * 200
    truncator = ContextTruncator()
    result = truncator.truncate(text, budget_tokens=100)
    assert len(result) < len(text)
    assert truncator.count_tokens(result) <= 100


def test_truncate_zero_budget_returns_empty():
    """预算 <= 0 返回空串"""
    assert ContextTruncator().truncate("abc", budget_tokens=0) == ""


# ---------------------------------------------------------------------------
# 重试策略
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_truncates_and_succeeds():
    """上下文超长错误后按预算重建上下文重试成功"""
    calls: list[str] = []
    policy = ContextWindowRetryPolicy()

    async def call(context: str) -> str:
        calls.append(context)
        if len(calls) == 1:
            raise RuntimeError("maximum context length is 100 tokens. However you requested 500 tokens.")
        return f"ok:{context}"

    def context_factory(budget: int | None) -> str:
        # 首次完整上下文；重试按预算截断
        full = "x" * 1000
        if budget is None:
            return full
        return full[: max(budget * 3, 10)]  # 简化：预算越大截取越多

    result = await policy.run(call, context_factory, model_code="test")
    assert result.startswith("ok:")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_retry_raises_on_unrelated_error():
    """非上下文超长错误直接抛出，不重试"""
    policy = ContextWindowRetryPolicy()
    calls: list[str] = []

    async def call(context: str) -> str:
        calls.append(context)
        raise ValueError("some other error")

    with pytest.raises(ValueError):
        await policy.run(call, lambda budget: "context", model_code="test")
    assert len(calls) == 1  # 未重试


@pytest.mark.asyncio
async def test_retry_exhausts_raises_original():
    """重试耗尽后抛出原始异常"""
    policy = ContextWindowRetryPolicy(max_attempts=2)
    calls: list[str] = []

    async def call(context: str) -> str:
        calls.append(context)
        raise RuntimeError("maximum context length is 100 tokens. However you requested 500 tokens.")

    with pytest.raises(RuntimeError):
        await policy.run(call, lambda budget: "ctx", model_code="test")
    assert len(calls) == 2  # 首次 + 重试 1 次后放弃
