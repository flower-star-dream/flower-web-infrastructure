"""
监控整改第六批（组 B）单元测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证规范整改：
              - S16-3 静态集合治理：线程池注册表容量上限 + 并发注册/采样快照遍历不抛错
              - S16-4 tokenizer 静态缓存有界 LRU（同一目录同实例、不同目录不串扰、LRU 淘汰）
              - S16-5 扩展点注册与生命周期绑定：CacheMetrics unregister 后可重新注册
              - S17-1 错误日志携带完整错误码：JsonFormatter 输出 error_code 字段
              - S17-2 本地文件+日志轮转：configure_logging 配置 log_file 后产生 .log 文件
"""
import json
import logging
import logging.handlers
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import web_infra.infra.monitoring.runtime_metrics as runtime_metrics_module
import web_infra.infra.utils.token_counter as token_counter_module
from web_infra.infra.logging import JsonFormatter, configure_logging
from web_infra.infra.monitoring.cache_metrics import CacheMetrics
from web_infra.infra.monitoring.component_metrics_interface import ComponentMetricsCollector
from web_infra.infra.monitoring.runtime_metrics import ThreadPoolMetrics


# ---------------------------------------------------------------------------
# S16-3：runtime_metrics 静态容器治理
# ---------------------------------------------------------------------------


def test_thread_pool_metrics_rejects_over_capacity(monkeypatch):
    """超过 _MAX_POOLS 上限的新 name 注册被拒绝（S16-3 静态容器有界）"""
    monkeypatch.setattr(runtime_metrics_module, "_MAX_POOLS", 2)
    # 记录测试前的既有注册项（全量运行时其他测试可能已注册，如 "test-pool"）
    preexisting = set(ThreadPoolMetrics._pools)
    pools = []
    try:
        for i in range(3):
            pool = ThreadPoolExecutor(max_workers=1)
            pools.append(pool)
            ThreadPoolMetrics.register(pool, f"cap-{i}")
        # 容量 = 上限 - 既有注册数：cap-0 可注册，cap-1/cap-2 因超限被拒绝
        assert set(ThreadPoolMetrics._pools) == preexisting | {"cap-0"}
        assert "cap-1" not in ThreadPoolMetrics._pools
        assert "cap-2" not in ThreadPoolMetrics._pools
        # 同名覆盖不受上限影响（不新增容量）
        pool = ThreadPoolExecutor(max_workers=1)
        pools.append(pool)
        ThreadPoolMetrics.register(pool, "cap-0")
        assert set(ThreadPoolMetrics._pools) == preexisting | {"cap-0"}
    finally:
        for name in list(ThreadPoolMetrics._pools):
            if name.startswith("cap-"):
                ThreadPoolMetrics.unregister(name)
        for pool in pools:
            pool.shutdown(wait=False)


def test_thread_pool_metrics_collect_concurrent():
    """并发注册/注销/采样不抛错（S16-3 快照遍历防 RuntimeError）"""
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            pool = ThreadPoolExecutor(max_workers=1)
            name = f"conc-{i}"
            ThreadPoolMetrics.register(pool, name)
            for _ in range(20):
                ThreadPoolMetrics.collect()
            ThreadPoolMetrics.unregister(name)
            pool.shutdown(wait=False)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert not [n for n in ThreadPoolMetrics._pools if n.startswith("conc-")]


# ---------------------------------------------------------------------------
# S16-4：token_counter tokenizer 缓存有界 LRU
# ---------------------------------------------------------------------------


class _FakeTokenizer:
    """模拟 PreTrainedTokenizerFast（仅验证缓存行为，不依赖 transformers 安装）"""

    def __init__(self, name: str) -> None:
        self.name = name

    def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
        return [1] * len(text)


@pytest.fixture(autouse=True)
def _clear_tokenizer_cache():
    """每个 token_counter 相关测试前后清空 lru_cache，避免测试间串扰"""
    token_counter_module._load_tokenizer_impl.cache_clear()
    yield
    token_counter_module._load_tokenizer_impl.cache_clear()


def test_tokenizer_cache_same_dir_same_instance(monkeypatch):
    """同一 tokenizer 目录返回同一实例、不同目录互不串扰（S16-4）"""
    monkeypatch.setattr(
        token_counter_module,
        "_load_tokenizer_from_disk",
        lambda d: _FakeTokenizer(d),
    )
    a1 = token_counter_module._load_tokenizer_impl("dir-a")
    a2 = token_counter_module._load_tokenizer_impl("dir-a")
    b = token_counter_module._load_tokenizer_impl("dir-b")
    assert a1 is a2
    assert a1 is not b
    assert a1.name == "dir-a"
    assert b.name == "dir-b"


def test_tokenizer_cache_hit_counts_loader_once(monkeypatch):
    """lru 缓存命中：同一目录二次获取不再调用底层加载函数"""
    calls: list[str] = []

    def fake_load(model_dir: str) -> _FakeTokenizer:
        calls.append(model_dir)
        return _FakeTokenizer(model_dir)

    monkeypatch.setattr(token_counter_module, "_load_tokenizer_from_disk", fake_load)
    token_counter_module._load_tokenizer_impl("dir-a")
    token_counter_module._load_tokenizer_impl("dir-a")
    assert calls == ["dir-a"]


def test_tokenizer_cache_lru_evicts_oldest(monkeypatch):
    """有界 LRU：超过 maxsize(4) 后最久未用的目录被淘汰并重新加载（S16-4 防无界增长）"""
    counter = 0

    def fake_load(model_dir: str) -> _FakeTokenizer:
        nonlocal counter
        counter += 1
        return _FakeTokenizer(f"{model_dir}#{counter}")

    monkeypatch.setattr(token_counter_module, "_load_tokenizer_from_disk", fake_load)
    for i in range(5):
        token_counter_module._load_tokenizer_impl(f"dir-{i}")

    info = token_counter_module._load_tokenizer_impl.cache_info()
    assert info.maxsize == 4
    assert info.currsize == 4

    # dir-0 是最久未用的，已被淘汰：再次访问触发重新加载
    again = token_counter_module._load_tokenizer_impl("dir-0")
    assert again.name.startswith("dir-0#")
    assert counter == 6  # 5 次初始加载 + 1 次淘汰后重载


def test_token_counter_load_tokenizer_returns_same_instance(monkeypatch):
    """TokenCounter._load_tokenizer 经有界缓存返回同一实例（对外行为兼容）"""
    monkeypatch.setattr(
        token_counter_module,
        "_load_tokenizer_from_disk",
        lambda d: _FakeTokenizer(d),
    )
    counter = token_counter_module.TokenCounter.get_instance()
    t1 = counter._load_tokenizer("dir-a")
    t2 = counter._load_tokenizer("dir-a")
    assert t1 is t2
    assert t1 is not counter._load_tokenizer("dir-b")


# ---------------------------------------------------------------------------
# S16-5：component_metrics / cache_metrics 卸载入口
# ---------------------------------------------------------------------------


def test_cache_metrics_unregister_then_register_again():
    """unregister 后再次 ensure 可重新注册（S16-5 生命周期绑定）"""
    CacheMetrics.ensure()
    assert CacheMetrics._registered
    CacheMetrics.unregister_metrics()
    assert not CacheMetrics._registered
    # 再次注册不抛重名异常，且记录功能正常
    CacheMetrics.ensure()
    CacheMetrics.record_operation("memory", "get", hit=True)
    assert CacheMetrics.operations_total is not None
    assert CacheMetrics.operations_total.labels("memory", "get")._value.get() >= 1


def test_cache_metrics_unregister_idempotent():
    """unregister 幂等：未注册/已卸载时再次调用不抛错"""
    CacheMetrics.unregister_metrics()
    CacheMetrics.unregister_metrics()
    assert not CacheMetrics._registered


def test_component_metrics_interface_unregister_not_implemented():
    """基类 unregister_metrics 为抽象卸载入口，未覆写子类调用抛 NotImplementedError"""
    with pytest.raises(NotImplementedError):
        ComponentMetricsCollector.unregister_metrics()


# ---------------------------------------------------------------------------
# S17-1：JsonFormatter 错误日志携带错误码
# ---------------------------------------------------------------------------


def _make_record(message: str, **extra) -> logging.LogRecord:
    """构造一条带额外字段的 LogRecord"""
    record = logging.LogRecord("test.json", logging.ERROR, __file__, 1, message, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_error_code_from_extra():
    """extra 携带 error_code 时 JSON 输出包含该字段（S17-1）"""
    record = _make_record("业务错误", error_code="E2-AUTH-000")
    output = json.loads(JsonFormatter().format(record))
    assert output["error_code"] == "E2-AUTH-000"


def test_json_formatter_error_code_default_empty():
    """未提供 error_code 时输出空字符串（向后兼容，不破坏既有字段）"""
    record = _make_record("普通错误")
    output = json.loads(JsonFormatter().format(record))
    assert output["error_code"] == ""
    assert "message" in output
    assert "level" in output


# ---------------------------------------------------------------------------
# S17-2：configure_logging 文件日志轮转
# ---------------------------------------------------------------------------


def test_configure_logging_writes_rotating_file(tmp_path):
    """配置 log_file 后产生 .log 文件且 handler 为 TimedRotatingFileHandler（S17-2）"""
    log_file = tmp_path / "app.log"
    configure_logging(level=logging.INFO, fmt="text", log_file=str(log_file))
    root = logging.getLogger()
    handlers = [h for h in root.handlers if getattr(h, "_web_infra", False)]
    assert any(isinstance(h, logging.handlers.TimedRotatingFileHandler) for h in handlers)
    logging.getLogger("web_infra.test.rotation").info("rotation hello")
    assert log_file.exists()
    assert "rotation hello" in log_file.read_text(encoding="utf-8")


def test_configure_logging_without_log_file_keeps_stream_only():
    """不传 log_file 时行为与原来一致：仅 StreamHandler（向后兼容）"""
    configure_logging(level=logging.INFO, fmt="text")
    root = logging.getLogger()
    handlers = [h for h in root.handlers if getattr(h, "_web_infra", False)]
    assert handlers
    assert all(not isinstance(h, logging.handlers.TimedRotatingFileHandler) for h in handlers)
    # 幂等：重复调用不累积 handler
    configure_logging(level=logging.INFO, fmt="text")
    handlers_after = [h for h in logging.getLogger().handlers if getattr(h, "_web_infra", False)]
    assert len(handlers_after) == 1
