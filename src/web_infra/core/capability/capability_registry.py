"""
能力注册表

@Author: 花海
@Date: 2026/08/17 16:00
@Description: 能力注册表（类级注册，全局装配）：登记能力契约（SPI）、维护依赖包含规则（requires）、
              提供解析（resolve，按拓扑序展开前置能力）、装配校验（validate）与启用
              （enable，按拓扑序自动导入前置能力与目标能力的框架模块，幂等）。
"""
from __future__ import annotations

import importlib
from threading import Lock
from typing import Iterable

from web_infra.core.capability.capability import Capability
from web_infra.core.capability.capability_error import CapabilityError
from web_infra.core.capability.capability_resolution import CapabilityResolution
from web_infra.core.capability.capability_validation import CapabilityValidation


class CapabilityRegistry:
    """能力注册表（类级注册，全局装配；类级锁保护并发 register，与 FeignClient 工厂一致）"""

    _capabilities: dict[str, Capability] = {}
    _lock = Lock()

    @classmethod
    def register(cls, capability: Capability) -> None:
        """登记能力契约（同名覆盖；前置能力允许后置注册，未知前置在解析/校验时拦截）。

        :param capability: 能力契约
        :raises CapabilityError: 能力名为空 / 前置包含自身
        """
        if not capability.name:
            raise CapabilityError("能力名不能为空")
        if capability.name in capability.requires:
            raise CapabilityError(f"能力 {capability.name} 不能依赖自身")
        with cls._lock:
            cls._capabilities[capability.name] = capability

    @classmethod
    def get(cls, name: str) -> Capability | None:
        """按能力名查询契约（未注册返回 None）。

        :param name: 能力名
        :return: 能力契约或 None
        """
        return cls._capabilities.get(name)

    @classmethod
    def names(cls) -> list[str]:
        """已登记能力名清单（按注册顺序）。"""
        return list(cls._capabilities)

    @classmethod
    def resolve(cls, name: str) -> CapabilityResolution:
        """解析能力：按依赖包含规则展开传递前置，返回拓扑序依赖链（前置在前，目标最后）。

        :param name: 目标能力名
        :return: 解析结果（能力链 + 需导入框架模块清单）
        :raises CapabilityError: 能力未注册 / 依赖链存在循环
        """
        chain, circular, unknown = cls._topological_closure({name})
        if unknown:
            raise CapabilityError(f"未注册的能力: {', '.join(sorted(unknown))}（可用: {', '.join(cls._capabilities)}）")
        if circular:
            raise CapabilityError("能力依赖存在循环: " + "; ".join(" -> ".join(c) for c in circular))
        modules: list[str] = []
        for cap in chain:
            for module in cap.modules:
                if module not in modules:
                    modules.append(module)
        return CapabilityResolution(name=name, chain=tuple(chain), modules=tuple(modules))

    @classmethod
    def validate(cls, enabled: Iterable[str]) -> CapabilityValidation:
        """装配校验：检查启用集合按包含关系展开后的完整性。

        未知能力 / 依赖循环 → ok=False 并给出明细；缺前置不视为失败（按包含关系自动补足，见 closure / chain）。

        :param enabled: 启用的能力名集合
        :return: 装配校验结果（未知能力 / 循环依赖 / 完整闭包 / 拓扑序）
        """
        chain, circular, unknown = cls._topological_closure(set(enabled))
        return CapabilityValidation(
            ok=not unknown and not circular,
            unknown=frozenset(unknown),
            circular=tuple(circular),
            closure=frozenset(cap.name for cap in chain),
            chain=tuple(cap.name for cap in chain),
        )

    @classmethod
    def enable(cls, name: str) -> CapabilityResolution:
        """启用能力：解析（校验通过）后按拓扑序自动导入前置能力与目标能力的框架模块（幂等）。

        :param name: 目标能力名
        :return: 解析结果
        :raises CapabilityError: 能力未注册 / 依赖链存在循环
        """
        resolution = cls.resolve(name)
        for module in resolution.modules:
            importlib.import_module(module)
        return resolution

    # ------------------------------------------------------------------
    # 内部：拓扑展开（依赖包含规则）
    # ------------------------------------------------------------------

    @classmethod
    def _topological_closure(cls, names: set[str]) -> tuple[list[Capability], list[tuple[str, ...]], set[str]]:
        """按依赖包含规则展开启用集合：返回 (拓扑序能力链, 循环链路明细, 未知能力集合)。

        递归 DFS 展开传递前置；环检测基于当前递归栈（visiting），环路径按栈内片段报告；
        未知能力计入 unknown 不中断展开；已处理能力（seen）不再重复入链（去重保序）。

        :param names: 待展开的能力名集合
        :return: (拓扑序能力链, 循环链路, 未知能力集合)
        """
        chain: list[Capability] = []
        seen: set[str] = set()
        circular: list[tuple[str, ...]] = []
        unknown: set[str] = set()
        visiting: list[str] = []

        def dfs(name: str) -> None:
            if name in seen:
                return
            capability = cls._capabilities.get(name)
            if capability is None:
                unknown.add(name)
                return
            if name in visiting:  # 环：name 已在当前递归栈
                cycle = tuple(visiting[visiting.index(name):] + [name])
                if cycle not in circular:
                    circular.append(cycle)
                return
            visiting.append(name)
            for requirement in capability.requires:
                dfs(requirement)
            visiting.pop()
            seen.add(name)
            chain.append(capability)

        for name in names:
            dfs(name)
        return chain, circular, unknown
