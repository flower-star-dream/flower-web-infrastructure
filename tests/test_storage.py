"""
对象存储抽象单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证本地对象存储的 put/get/delete/exists 行为（规范 §22）。
"""
import pytest

from web_infra.capabilities.storage import LocalObjectStorage, StorageConfig


@pytest.mark.asyncio
async def test_put_get_delete(tmp_path):
    """上传、下载、删除与存在性判断"""
    storage = LocalObjectStorage(StorageConfig(base_dir=str(tmp_path)))
    await storage.put("bucket", "k", b"hello")

    assert await storage.exists("bucket", "k") is True
    assert await storage.get("bucket", "k") == b"hello"

    await storage.delete("bucket", "k")
    assert await storage.exists("bucket", "k") is False
    assert await storage.get("bucket", "k") is None


@pytest.mark.asyncio
async def test_get_missing_returns_none(tmp_path):
    """读取不存在对象返回 None"""
    storage = LocalObjectStorage(StorageConfig(base_dir=str(tmp_path)))
    assert await storage.get("bucket", "nope") is None
