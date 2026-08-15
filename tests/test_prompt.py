"""
提示词模板管理单元测试

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 验证占位符提取/填充、嵌套哨兵保护、未替换检测与模板存储（AI 规范 §6.1/§6.2）。
"""
import pytest

from web_infra.ai import PromptTemplate, PromptTemplateFiller, PromptTemplateStoreInterface
from web_infra.ai.prompt import InMemoryPromptTemplateStore


@pytest.mark.asyncio
async def test_extract_variables():
    """占位符提取：去重保序、不误匹配 jinja2 双花括号"""
    filler = PromptTemplateFiller()
    assert filler.extract_variables("你好 {name}，今天是 {date}，{name} 再见") == ["name", "date"]
    assert filler.extract_variables("{{ not_var }} 和 {ok}") == ["ok"]


def test_fill_basic():
    """基础填充"""
    filler = PromptTemplateFiller()
    result = filler.fill("用户：{username}，角色：{role}", {"username": "alice", "role": "admin"})
    assert result == "用户：alice，角色：admin"


def test_fill_unfilled_raises():
    """未替换占位符抛 ValueError"""
    filler = PromptTemplateFiller()
    with pytest.raises(ValueError):
        filler.fill("用户：{username}，{missing}", {"username": "alice"})


def test_fill_unfilled_allowed_when_flag_false():
    """raise_on_unfilled=False 时保留未替换占位符"""
    filler = PromptTemplateFiller()
    result = filler.fill("用户：{username}，{missing}", {"username": "alice"}, raise_on_unfilled=False)
    assert "{missing}" in result


def test_nested_placeholder_protection():
    """变量值中的嵌套 {xxx} 不被二次替换误伤"""
    filler = PromptTemplateFiller()
    # 变量值含 {disease} 占位符，但 {disease} 不在模板中，应保持原样
    result = filler.fill("报告：{report}", {"report": "疾病 {disease} 说明"})
    assert result == "报告：疾病 {disease} 说明"


def test_value_with_same_key_placeholder_filled():
    """变量值含与模板同名的占位符时正常替换自身"""
    filler = PromptTemplateFiller()
    result = filler.fill("{name} 说 {name} 好", {"name": "alice"})
    assert result == "alice 说 alice 好"


@pytest.mark.asyncio
async def test_memory_store_roundtrip():
    """内存存储：保存后可加载，版本匹配"""
    store = InMemoryPromptTemplateStore()
    template = PromptTemplate(key="report.comprehensive", version="2.0.0", content="综合报告：{summary}")
    await store.save(template)
    loaded = await store.load("report.comprehensive")
    assert loaded is not None
    assert loaded.version == "2.0.0"
    assert loaded.fingerprint == "report.comprehensive:2.0.0"
    # 指定不存在的版本返回 None
    assert await store.load("report.comprehensive", version="9.9.9") is None
    # 未保存的 key 返回 None
    assert await store.load("unknown.key") is None


@pytest.mark.asyncio
async def test_store_is_spi():
    """存储遵循 SPI：业务可自定义实现"""
    assert issubclass(InMemoryPromptTemplateStore, PromptTemplateStoreInterface)
