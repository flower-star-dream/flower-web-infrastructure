"""
数据库访问抽象单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证分页参数与 sqlite 参考实现的 CRUD/事务行为（规范 §10 / §12.3）。
"""
import pytest

from web_infra.capabilities.db import PageQuery, SqliteSessionFactory


def test_page_query_offset():
    """分页参数 offset/limit 计算（pageNo 从 1 开始）"""
    query = PageQuery(page_no=3, page_size=20)
    assert query.offset == 40
    assert query.limit == 20


def test_sqlite_crud():
    """sqlite 参考实现：建表、插入、查询"""
    factory = SqliteSessionFactory()
    session = factory.create_session()
    session.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    session.execute("INSERT INTO t (name) VALUES (?)", ("a",))

    assert session.query_all("SELECT * FROM t") == [{"id": 1, "name": "a"}]
    assert session.query_one("SELECT * FROM t WHERE id=?", (1,))["name"] == "a"
    factory.close()


def test_sqlite_transaction_rollback():
    """事务异常回滚"""
    factory = SqliteSessionFactory()
    session = factory.create_session()
    session.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")

    with pytest.raises(RuntimeError):
        with session.transaction():
            session.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("boom")

    assert session.query_all("SELECT * FROM t") == []
    factory.close()


def test_sqlite_transaction_commit():
    """事务正常提交"""
    factory = SqliteSessionFactory()
    session = factory.create_session()
    session.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")

    with session.transaction():
        session.execute("INSERT INTO t VALUES (1)")

    assert len(session.query_all("SELECT * FROM t")) == 1
    factory.close()
