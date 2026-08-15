"""
分片上传/断点续传单元测试

@Author: 花海
@Date: 2026/08/14 19:30
@Description: 验证初始化分片计算、逐片上传、断点续传列出、合并完整性校验/大小校验/MD5 校验、
              文件类型校验（规范 §22.2 魔数+后缀白名单）与临时任务清理（规范 §22.4）。
              使用本地分片存储 + 内存任务存储。
"""
import hashlib

import pytest

from web_infra.storage.upload import (
    FileTypeValidator,
    InMemoryUploadStore,
    LocalPartStorage,
    MultipartUploadService,
)

# PNG 魔数（\x89PNG\r\n\x1a\n，文件头 8 字节），测试内容统一以该签名开头通过类型校验
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _chunk(content: bytes, chunk_size: int) -> bytes:
    """将内容补齐到指定分片大小（不足补 'x'，首字节保留魔数头）"""
    return content.ljust(chunk_size, b"x")


@pytest.fixture()
def service(tmp_path):
    """本地分片上传服务（临时目录）"""
    store = InMemoryUploadStore()
    parts = LocalPartStorage(str(tmp_path / "parts"))
    return MultipartUploadService(store, parts, default_chunk_size=100), store, tmp_path


def _make_service(tmp_path, **kwargs):
    """按参数构造本地分片上传服务（用于大小上限等专项测试）"""
    store = InMemoryUploadStore()
    parts = LocalPartStorage(str(tmp_path / "parts"))
    return MultipartUploadService(store, parts, default_chunk_size=100, **kwargs), store, tmp_path


@pytest.mark.asyncio
async def test_initialize_small_file_single_chunk(service):
    """小文件：单分片整体上传"""
    svc, _, _ = service
    task = await svc.initialize("small.txt", 50)
    assert task.total_chunks == 1
    assert task.chunk_size == 50


@pytest.mark.asyncio
async def test_initialize_large_file_auto_chunks(service):
    """大文件（>50MB）：自动按默认分片大小分片"""
    svc, _, _ = service
    large = MultipartUploadService.LARGE_FILE_THRESHOLD + 10
    task = await svc.initialize("big.png", large)
    assert task.total_chunks > 1
    assert task.chunk_size == 100  # 测试用默认 100 字节分片


@pytest.mark.asyncio
async def test_initialize_large_file_must_chunk(service):
    """大文件明确不分片（chunk_size=0）抛错（规范 §22.4 必须分片）"""
    svc, _, _ = service
    with pytest.raises(ValueError):
        await svc.initialize("big.png", MultipartUploadService.LARGE_FILE_THRESHOLD + 1, chunk_size=0)


@pytest.mark.asyncio
async def test_initialize_rejects_disallowed_extension(service):
    """后缀白名单校验：可执行/脚本文件拒绝上传（规范 §22.2）"""
    svc, _, _ = service
    with pytest.raises(ValueError, match="不支持的文件类型"):
        await svc.initialize("malware.exe", 10)
    with pytest.raises(ValueError, match="不支持的文件类型"):
        await svc.initialize("shell.sh", 10)
    with pytest.raises(ValueError, match="不支持的文件类型"):
        await svc.initialize("no_extension", 10)


@pytest.mark.asyncio
async def test_upload_part_magic_validation(service):
    """首片内容魔数校验：魔数不匹配拒绝（防改名绕过，规范 §22.2）"""
    svc, _, _ = service
    task = await svc.initialize("data.png", 100, chunk_size=100)
    # 后缀为 png 但内容不是 PNG 魔数 -> 拒绝
    with pytest.raises(ValueError, match="魔数"):
        await svc.upload_part(task.upload_id, 1, b"x" * 100)


@pytest.mark.asyncio
async def test_upload_and_resume_parts(service):
    """逐片上传 + 断点续传列出已上传分片"""
    svc, _, _ = service
    task = await svc.initialize("data.png", 250, chunk_size=100)
    await svc.upload_part(task.upload_id, 1, _chunk(PNG_MAGIC + b"a", 100))
    await svc.upload_part(task.upload_id, 3, b"c" * 50)
    assert await svc.list_uploaded_parts(task.upload_id) == [1, 3]  # 断点续传：缺 2


@pytest.mark.asyncio
async def test_upload_part_validation(service):
    """分片序号越界 / 分片超大小抛错"""
    svc, _, _ = service
    task = await svc.initialize("data.png", 100, chunk_size=100)
    with pytest.raises(ValueError):
        await svc.upload_part(task.upload_id, 0, b"x")
    with pytest.raises(ValueError):
        await svc.upload_part(task.upload_id, 2, b"x")  # total=1，序号 2 越界
    with pytest.raises(ValueError):
        await svc.upload_part(task.upload_id, 1, b"x" * 101)  # 超分片大小


@pytest.mark.asyncio
async def test_complete_incomplete_parts_rejected(service):
    """分片不完整：合并拒绝（规范 §22.4 合并前校验分片完整性）"""
    svc, _, _ = service
    task = await svc.initialize("data.png", 150, chunk_size=100)
    await svc.upload_part(task.upload_id, 1, _chunk(PNG_MAGIC + b"a", 100))
    with pytest.raises(ValueError, match="分片不完整"):
        await svc.complete(task.upload_id)


@pytest.mark.asyncio
async def test_complete_merges_and_cleans(service):
    """完整分片合并成功：返回对象 Key，大小校验通过，分片清理"""
    svc, _, parts_dir = service
    task = await svc.initialize("data.png", 250, chunk_size=100)
    await svc.upload_part(task.upload_id, 1, _chunk(PNG_MAGIC + b"a", 100))
    await svc.upload_part(task.upload_id, 2, b"b" * 100)
    await svc.upload_part(task.upload_id, 3, b"c" * 50)

    object_key = await svc.complete(task.upload_id)
    assert object_key.endswith("data.png")
    # 分片临时文件已清理
    import os

    assert not os.path.isdir(os.path.join(str(parts_dir), task.upload_id))


@pytest.mark.asyncio
async def test_complete_md5_validation(service):
    """合并 MD5 校验：一致成功，不一致拒绝"""
    svc, _, _ = service
    content = PNG_MAGIC + b"hello"  # 13 字节
    task = await svc.initialize("data.png", len(content), chunk_size=len(content))
    await svc.upload_part(task.upload_id, 1, content)
    expected = hashlib.md5(content).hexdigest()
    assert await svc.complete(task.upload_id, expected_md5=expected)

    task2 = await svc.initialize("data2.png", len(content), chunk_size=len(content))
    await svc.upload_part(task2.upload_id, 1, content)
    with pytest.raises(ValueError, match="MD5"):
        await svc.complete(task2.upload_id, expected_md5="deadbeef")


@pytest.mark.asyncio
async def test_cleanup_stale_tasks(service):
    """过期未完成任务记录清理（规范 §22.4 临时任务记录 TTL）"""
    svc, store, _ = service
    task = await svc.initialize("old.png", 10)
    # 模拟任务创建于 2 天前（TTL 24h 已过期）
    from datetime import datetime, timedelta, timezone

    async with store._lock:
        store._tasks[task.upload_id].created_at = datetime.now(timezone.utc) - timedelta(days=2)
    assert await svc.cleanup_stale(ttl_hours=24) == 1
    assert await store.get(task.upload_id) is None


@pytest.mark.asyncio
async def test_cancel_only_removes_target_task(service):
    """cancel 仅清理当前任务，不得误删其他进行中的任务（规范 §22.4 禁止误删）"""
    svc, store, _ = service
    target = await svc.initialize("target.png", 10, chunk_size=5)
    other = await svc.initialize("other.png", 10, chunk_size=5)

    await svc.cancel(target.upload_id)

    assert await store.get(target.upload_id) is None
    assert await store.get(other.upload_id) is not None


def test_file_type_validator_default_whitelist():
    """默认白名单：常见类型允许，可执行/脚本/无后缀拒绝"""
    validator = FileTypeValidator()
    validator.validate_extension("photo.png")
    validator.validate_extension("doc.pdf")
    with pytest.raises(ValueError):
        validator.validate_extension("run.exe")
    with pytest.raises(ValueError):
        validator.validate_extension("script.js")
    with pytest.raises(ValueError):
        validator.validate_extension("README")


def test_file_type_validator_magic():
    """魔数校验：匹配签名通过，不匹配拒绝"""
    validator = FileTypeValidator()
    validator.validate_magic(b"\x89PNG\r\n\x1a\nrest")
    validator.validate_magic(b"%PDF-1.4")
    with pytest.raises(ValueError):
        validator.validate_magic(b"not-a-real-signature")


@pytest.mark.asyncio
async def test_initialize_respects_max_upload_size(tmp_path):
    """上传大小上限生效：超过上限拒绝，等于上限允许（规范 §22.2）"""
    svc, _, _ = _make_service(tmp_path, max_upload_size=100)
    with pytest.raises(ValueError, match="超过上传大小上限"):
        await svc.initialize("data.png", 101)
    task = await svc.initialize("data.png", 100)
    assert task.file_size == 100


@pytest.mark.asyncio
async def test_initialize_no_max_upload_size_unlimited(tmp_path):
    """未配置 max_upload_size（None）不限制大小"""
    svc, _, _ = _make_service(tmp_path, max_upload_size=None)
    task = await svc.initialize("data.png", 10 * 1024 * 1024)
    assert task.file_size == 10 * 1024 * 1024


@pytest.mark.asyncio
async def test_cleanup_expired_removes_stale_dirs(tmp_path):
    """过期分片目录被清理、未过期保留（规范 §22.4 临时目录 TTL）"""
    import os
    from datetime import datetime, timedelta

    parts = LocalPartStorage(str(tmp_path / "parts"))
    base = os.path.join(str(tmp_path), "parts")
    os.makedirs(os.path.join(base, "stale_task"), exist_ok=True)
    os.makedirs(os.path.join(base, "fresh_task"), exist_ok=True)
    # stale 目录 mtime 置为 2 天前（过期），fresh 目录保持最新（未过期）
    stale_time = (datetime.now() - timedelta(days=2)).timestamp()
    os.utime(os.path.join(base, "stale_task"), (stale_time, stale_time))

    before = datetime.now() - timedelta(hours=24)
    assert await parts.cleanup_expired(before) == 1
    assert not os.path.isdir(os.path.join(base, "stale_task"))
    assert os.path.isdir(os.path.join(base, "fresh_task"))


@pytest.mark.asyncio
async def test_cleanup_stale_links_part_cleanup(tmp_path):
    """cleanup_stale 联动清理过期分片目录（任务记录 + 分片目录）"""
    import os
    from datetime import datetime, timedelta, timezone

    svc, store, tmp = _make_service(tmp_path)
    task = await svc.initialize("old.png", 10)
    # 模拟任务创建于 2 天前（任务记录过期）
    async with store._lock:
        store._tasks[task.upload_id].created_at = datetime.now(timezone.utc) - timedelta(days=2)
    # 模拟同任务过期分片目录已落盘（目录 mtime 置为 2 天前）
    base = os.path.join(str(tmp), "parts")
    task_dir = os.path.join(base, task.upload_id)
    os.makedirs(task_dir, exist_ok=True)
    stale_time = (datetime.now() - timedelta(days=2)).timestamp()
    os.utime(task_dir, (stale_time, stale_time))

    assert await svc.cleanup_stale(ttl_hours=24) == 2  # 任务记录 1 + 分片目录 1
    assert await store.get(task.upload_id) is None
    assert not os.path.isdir(task_dir)
