"""
统一扩展注册器

@Author: 花海
@Date: 2026/08/18 14:00
@Description: 统一扩展注册器（类级注册，全局装配）：登记扩展点契约（ExtensionPoint），
              维护依赖包含规则（requires），提供解析（resolve，按拓扑序展开前置扩展点）、
              装配校验（validate：未知扩展点/依赖循环）与查询/注销能力。
              与领域注册表（DatabaseRegistry/CacheBackendRegistry 等）的关系是"上层编排层"：
              领域注册表按名管资源工厂（装配期实例化），扩展注册器管插件协议对象
              （build/startup/shutdown 生命周期 + 依赖顺序），业务插件经 register 注册后
              在 app.extensions.enabled 声明即启用，无需改动框架装配代码。
"""
from __future__ import annotations

from threading import Lock
from typing import ClassVar, Iterable

from web_infra.core.extension.extension import ExtensionPoint
from web_infra.core.extension.extension_error import ExtensionError
from web_infra.core.extension.extension_resolution import ExtensionResolution
from web_infra.core.extension.extension_validation import ExtensionValidation


class ExtensionRegistry:
    """统一扩展注册器（类级注册，全局装配；类级锁保护并发 register，与 CapabilityRegistry 一致）"""

    _extensions: ClassVar[dict[str, ExtensionPoint]] = {}
    _lock = Lock()

    @classmethod
    def register(cls, extension: ExtensionPoint, overwrite: bool = False) -> None:
        """登记扩展点契约（同名默认拒绝，显式 overwrite=True 才覆盖内置/已注册扩展点）。

        :param extension: 扩展点契约
        :param overwrite: 同名已存在时是否显式覆盖（默认 False，避免误覆盖）
        :raises ExtensionError: 扩展点名为空 / 依赖自身 / 同名已存在且未显式覆盖
        """
        if not extension.name:
            raise ExtensionError("扩展点名不能为空")
        if extension.name in extension.requires:
            raise ExtensionError(f"扩展点 {extension.name} 不能依赖自身")
        with cls._lock:
            existing = cls._extensions.get(extension.name)
            if existing is not None and not overwrite:
                raise ExtensionError(
                    f"扩展点 {extension.name} 已注册（覆盖需 register(..., overwrite=True)）"
                )
            cls._extensions[extension.name] = extension

    @classmethod
    def get(cls, name: str) -> ExtensionPoint | None:
        """按扩展点名查询契约（未注册返回 None）。"""
        return cls._extensions.get(name)

    @classmethod
    def names(cls) -> list[str]:
        """已登记扩展点名清单（按注册顺序）。"""
        return list(cls._extensions)

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销扩展点（不存在时静默）。"""
        with cls._lock:
            cls._extensions.pop(name, None)

    @classmethod
    def resolve(cls, name: str) -> ExtensionResolution:
        """解析扩展点：按依赖包含规则展开传递前置，返回拓扑序扩展点链（前置在前，目标最后）。

        :param name: 目标扩展点名
        :return: 解析结果（拓扑序扩展点链）
        :raises ExtensionError: 扩展点未注册 / 依赖链存在循环
        """
        chain, circular, unknown = cls._topological_closure({name})
        if unknown:
            raise ExtensionError(
                f"未注册的扩展点: {', '.join(sorted(unknown))}（可用: {', '.join(cls._extensions)}）"
            )
        if circular:
            raise ExtensionError(
                "扩展点依赖存在循环: " + "; ".join(" -> ".join(c) for c in circular)
            )
        return ExtensionResolution(name=name, chain=tuple(chain))

    @classmethod
    def validate(cls, enabled: Iterable[str]) -> ExtensionValidation:
        """装配校验：检查启用集合按依赖包含规则展开后的完整性。

        未知扩展点 / 依赖循环 → ok=False 并给出明细；缺前置不视为失败
        （按包含关系自动补足，见 closure / chain）。

        :param enabled: 启用的扩展点名集合
        :return: 装配校验结果（未知扩展点 / 循环依赖 / 完整闭包 / 拓扑序）
        """
        chain, circular, unknown = cls._topological_closure(set(enabled))
        return ExtensionValidation(
            ok=not unknown and not circular,
            unknown=frozenset(unknown),
            circular=tuple(circular),
            closure=frozenset(cap.name for cap in chain),
            chain=tuple(cap.name for cap in chain),
        )

    # ------------------------------------------------------------------
    # 内部：拓扑展开（依赖包含规则）
    # ------------------------------------------------------------------

    @classmethod
    def _topological_closure(
        cls, names: set[str]
    ) -> tuple[list[ExtensionPoint], list[tuple[str, ...]], set[str]]:
        """按依赖包含规则展开启用集合：返回 (拓扑序扩展点链, 循环链路明细, 未知扩展点名集合)。

        递归 DFS 展开传递前置；环检测基于当前递归栈（visiting），环路径按栈内片段报告；
        未知扩展点计入 unknown 不中断展开；已处理扩展点（seen）不再重复入链（去重保序）。

        :param names: 待展开的扩展点名集合
        :return: (拓扑序扩展点链, 循环链路, 未知扩展点名集合)
        """
        chain: list[ExtensionPoint] = []
        seen: set[str] = set()
        circular: list[tuple[str, ...]] = []
        unknown: set[str] = set()
        visiting: list[str] = []

        def dfs(name: str) -> None:
            if name in seen:
                return
            extension = cls._extensions.get(name)
            if extension is None:
                unknown.add(name)
                return
            if name in visiting:  # 环：name 已在当前递归栈
                cycle = tuple(visiting[visiting.index(name):] + [name])
                if cycle not in circular:
                    circular.append(cycle)
                return
            visiting.append(name)
            for requirement in extension.requires:
                dfs(requirement)
            visiting.pop()
            seen.add(name)
            chain.append(extension)

        for name in names:
            dfs(name)
        return chain, circular, unknown
