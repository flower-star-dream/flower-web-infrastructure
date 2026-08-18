"""
统一响应结构与分页结构单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证 Result / PageResult 结构（规范 §4.7 / §12.3）。
"""
from web_infra.infra.result import Result, PageResult


def test_result_success():
    """成功响应 code=S0000"""
    result = Result.success(data={"id": 1})
    assert result.code == "S0000"
    assert result.message == "ok"
    assert result.data == {"id": 1}


def test_result_failure():
    """失败响应携带错误码，data 默认 null"""
    result = Result.failure("E4-ORDER-001", "订单不存在")
    assert result.code == "E4-ORDER-001"
    assert result.message == "订单不存在"
    assert result.data is None


def test_page_result():
    """分页响应 data.list + data.total"""
    page = PageResult.success(records=[{"id": 1}, {"id": 2}], total=2)
    assert page.code == "S0000"
    assert page.data.items == [{"id": 1}, {"id": 2}]
    assert page.data.total == 2
    # JSON 序列化键为 list（规范 §12.3）
    dumped = page.model_dump(by_alias=True)
    assert dumped["data"]["list"] == [{"id": 1}, {"id": 2}]
    assert dumped["data"]["total"] == 2
