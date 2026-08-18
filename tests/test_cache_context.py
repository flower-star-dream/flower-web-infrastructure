"""
缓存 Key 构建器与请求上下文单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证 KeyBuilder 占位符注入与动态段校验（§5.6），
              以及 RequestContext 上下文设置/清理（§6.5 / §17.4）。
"""
import pytest

from web_infra.capabilities.cache import KeyBuilder
from web_infra.infra.context import RequestContext, generate_trace_id
from web_infra.infra.error import ParamException


def test_key_builder_basic():
    """占位符模板按位置注入动态段"""
    assert KeyBuilder.build("web:order:v1:detail:{id}", 1001) == "web:order:v1:detail:1001"


def test_key_builder_multiple_placeholders():
    """多占位符注入"""
    template = "web:{tenantId}:user:v1:detail:{id}"
    assert KeyBuilder.build(template, "t1", "u2") == "web:t1:user:v1:detail:u2"


def test_key_builder_empty_segment_raises():
    """动态段为空抛出参数异常（§5.6 动态段校验）"""
    with pytest.raises(ParamException):
        KeyBuilder.build("web:order:v1:detail:{id}", "")


def test_key_builder_illegal_segment_raises():
    """动态段含非法字符（分隔符）抛出参数异常"""
    with pytest.raises(ParamException):
        KeyBuilder.build("web:order:v1:detail:{id}", "a:b")


def test_request_context_roundtrip():
    """请求上下文 set/get 与清理"""
    trace_id = generate_trace_id()
    assert len(trace_id) == 32

    RequestContext.set_trace_id(trace_id)
    RequestContext.set_user_id("1001")
    assert RequestContext.get_trace_id() == trace_id
    assert RequestContext.get_user_id() == "1001"

    RequestContext.clear()
    assert RequestContext.get_trace_id() == ""
    assert RequestContext.get_user_id() == "anonymous"  # 无用户上下文占位


def test_request_context_snapshot_restore():
    """上下文快照与恢复（异步/跨线程传递）"""
    RequestContext.set_trace_id("trace-1")
    snapshot = RequestContext.snapshot()

    RequestContext.clear()
    assert RequestContext.get_trace_id() == ""

    RequestContext.restore(snapshot)
    assert RequestContext.get_trace_id() == "trace-1"
