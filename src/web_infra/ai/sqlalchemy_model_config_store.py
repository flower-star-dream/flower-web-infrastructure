"""
SQLAlchemy 模型配置来源

@Author: 花海
@Date: 2026/08/17 15:00
@Description: 基于 SQLAlchemy AsyncSession + text() 的数据库模型配置来源（AI 规范 §3.2/§17.4）。
              模型配置统一收敛于数据库 ai_model_config 表（字段与 db/init/ddl/002-ai-model-config-init-ddl.sql 对齐），
              页面化配置新增/修改经 upsert 幂等落库（AI 规范 §17.4：页面化新增自动同步至配置中心/注册表）；
              api_key 列仅存 ``env:VAR`` 环境变量引用（规范 §3.1/AI-7：禁止明文落盘，可通过 .env 注入真实密钥），
              由 ModelConfig.resolved_api_key 运行时解析。
              测试可用 sqlite+aiosqlite 内存库验证 SQL 语义（SQL 为通用 ANSI 子集）。
"""
from __future__ import annotations

import inspect
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from web_infra.ai.model_config import ModelConfig
from web_infra.ai.model_config_store_interface import ModelConfigStoreInterface

# 表名与 db/init/ddl/002-ai-model-config-init-ddl.sql 基线 DDL 对齐
_MODEL_CONFIG_TABLE = "ai_model_config"
_COLUMNS = (
    "id, model_code, model_name, provider, api_base, api_key, model_id, "
    "max_tokens, temperature, top_p, timeout, is_deterministic, stop, "
    "input_price_per_1k, output_price_per_1k, created_at, updated_at"
)
# upsert 更新列（id/model_code/created_at 不参与更新，更新时回写 updated_at）
_UPDATE_COLUMNS = (
    "model_name, provider, api_base, api_key, model_id, max_tokens, "
    "temperature, top_p, timeout, is_deterministic, stop, "
    "input_price_per_1k, output_price_per_1k, updated_at"
)


def _now() -> datetime:
    """当前 UTC 时间（naive，兼容 MySQL DATETIME / SQLite 无时区列）"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SqlAlchemyModelConfigStore(ModelConfigStoreInterface):
    """SQLAlchemy 数据库模型配置来源（ai_model_config 表，AsyncSession + text()）"""

    def __init__(self, session_factory: Callable[[], AsyncSession] | Any, engine: Any | None = None) -> None:
        """初始化存储。

        :param session_factory: 异步会话工厂（`async_sessionmaker[AsyncSession]` 或 `() -> AsyncSession`）；
            load/load_all/upsert 内部自建会话并提交，可传入业务会话扩展同事务场景
        :param engine: 可选 SQLAlchemy 异步引擎（sqlite 场景由装配层自建独立 aiosqlite 引擎，
            持有引用供 close 释放；mysql 场景复用数据库组件引擎，传 None 即可）
        """
        self._session_factory = session_factory
        self._engine = engine

    async def close(self) -> None:
        """释放自建异步引擎（sqlite 场景独立 aiosqlite 引擎；mysql 场景复用 db 组件引擎，无操作）"""
        engine = self._engine
        if engine is None:
            return
        dispose = getattr(engine, "dispose", None)
        if callable(dispose):
            result = dispose()
            if inspect.isawaitable(result):
                await result

    @asynccontextmanager
    async def _session_scope(self, session: AsyncSession | None = None) -> AsyncGenerator[AsyncSession, None]:
        """会话作用域：无外部会话时自建并提交/关闭；传入业务会话时不提交（由业务事务统一提交）"""
        own = session is None
        current = session or self._session_factory()
        try:
            yield current
            if own:
                await current.commit()
        except Exception:
            if own:
                await current.rollback()
            raise
        finally:
            if own:
                await current.close()

    async def load(self, model_code: str | None = None) -> ModelConfig | None:
        """按模型逻辑名加载模型配置，未找到返回 None。

        未传 model_code（默认模型场景）时返回按 id 升序的首条配置，与 DictModelConfigStore 默认语义对齐。
        """
        from sqlalchemy import text

        async with self._session_scope() as session:
            if model_code:
                rows = (
                    await session.execute(
                        text(f"SELECT {_COLUMNS} FROM {_MODEL_CONFIG_TABLE} "
                             "WHERE model_code = :model_code LIMIT 1"),
                        {"model_code": model_code},
                    )
                ).mappings().all()
            else:
                rows = (
                    await session.execute(
                        text(f"SELECT {_COLUMNS} FROM {_MODEL_CONFIG_TABLE} ORDER BY id ASC LIMIT 1")
                    )
                ).mappings().all()
            return self._from_row(dict(rows[0])) if rows else None

    async def load_all(self) -> list[ModelConfig]:
        """加载全部模型配置（页面化配置自动注册依据，规范 §17.4/§3.2）"""
        from sqlalchemy import text

        async with self._session_scope() as session:
            rows = (
                await session.execute(
                    text(f"SELECT {_COLUMNS} FROM {_MODEL_CONFIG_TABLE} ORDER BY id ASC")
                )
            ).mappings().all()
            return [self._from_row(dict(row)) for row in rows]

    async def upsert(self, config: ModelConfig) -> ModelConfig:
        """幂等写入模型配置（页面化配置入口，AI 规范 §17.4）：按 model_code 存在即更新、缺失即插入。

        api_key 入参应为 ``env:VAR`` 引用或配置中心密钥标识（禁止明文落盘，AI 规范 §3.1/AI-7）；
        插入场景由数据库自增 id 决定主键，返回携带落库 id 的新配置。

        :param config: 待写入的模型配置
        :return: 落库后的模型配置（插入时回填数据库自增 id）
        """
        from sqlalchemy import text

        async with self._session_scope() as session:
            exists = (
                await session.execute(
                    text(f"SELECT 1 FROM {_MODEL_CONFIG_TABLE} WHERE model_code = :model_code LIMIT 1"),
                    {"model_code": config.model_code},
                )
            ).first()
            now = _now()
            if exists:
                params = self._bind(config, now)
                params["model_code"] = config.model_code
                await session.execute(
                    text(
                        f"UPDATE {_MODEL_CONFIG_TABLE} SET "
                        f"{', '.join(f'{col} = :{col}' for col in _UPDATE_COLUMNS.split(', '))} "
                        "WHERE model_code = :model_code"
                    ),
                    params,
                )
                return config
            result = await session.execute(
                text(
                    f"INSERT INTO {_MODEL_CONFIG_TABLE} ({_COLUMNS}) VALUES "
                    f"({', '.join(f':{col}' for col in _COLUMNS.split(', '))})"
                ),
                self._bind(config, now),
            )
            new_id = int(getattr(result, "lastrowid", 0) or config.id)
            return replace(config, id=new_id)

    # ------------------------------------------------------------------
    # 内部：行/配置互转
    # ------------------------------------------------------------------

    @staticmethod
    def _bind(config: ModelConfig, now: datetime) -> dict[str, Any]:
        """ModelConfig -> SQL 绑定参数（id 为 0 占位时传 None 由数据库自增；stop 列表 JSON 化）"""
        return {
            "id": config.id or None,
            "model_code": config.model_code,
            "model_name": config.model_name,
            "provider": config.provider,
            "api_base": config.api_base,
            "api_key": config.api_key,
            "model_id": config.model_id,
            "max_tokens": config.max_tokens,
            "temperature": float(config.temperature),
            "top_p": float(config.top_p),
            "timeout": config.timeout,
            "is_deterministic": 1 if config.is_deterministic else 0,
            "stop": json.dumps(config.stop, ensure_ascii=False) if isinstance(config.stop, list) else config.stop,
            "input_price_per_1k": float(config.input_price_per_1k),
            "output_price_per_1k": float(config.output_price_per_1k),
            "created_at": now,
            "updated_at": now,
        }

    @classmethod
    def _from_row(cls, row: dict[str, Any]) -> ModelConfig:
        """SQL 行 -> ModelConfig（stop JSON 反序列化，Decimal/字符串数值归一为 float）"""
        stop = row.get("stop")
        if stop:
            try:
                parsed = json.loads(stop)
                stop = parsed if isinstance(parsed, list) else stop
            except (TypeError, ValueError):
                pass  # 非 JSON（单字符串停止词）保持原样
        return ModelConfig(
            id=int(row["id"]),
            model_code=str(row["model_code"]),
            model_name=str(row["model_name"]),
            provider=str(row["provider"]),
            api_base=str(row["api_base"]),
            api_key=str(row["api_key"]),
            model_id=str(row["model_id"]) if row.get("model_id") else None,
            max_tokens=int(row["max_tokens"]),
            temperature=float(row["temperature"] or 0),
            top_p=float(row["top_p"] or 0),
            timeout=int(row["timeout"]),
            is_deterministic=bool(row["is_deterministic"]),
            stop=stop,
            input_price_per_1k=float(row["input_price_per_1k"] or 0),
            output_price_per_1k=float(row["output_price_per_1k"] or 0),
        )
