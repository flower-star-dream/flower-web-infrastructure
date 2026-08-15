"""
PDF 渲染导出组件

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 基于 Playwright 无头浏览器渲染 URL/HTML 导出 PDF（规范 §22 导出类通用能力）。
              浏览器实例单例懒加载（asyncio.Lock 保护）；支持超时、忽略 HTTPS 证书校验、
              登录态注入钩子（渲染需鉴权页面时通过 add_init_script 注入前端登录态）。
              playwright 为可选依赖（pip install -e ".[pdf]"），未安装时调用 render 抛 ImportError。
              注意：Windows 下需运行在 ProactorEventLoop（uvloop 不可用），后端渲染建议独立线程承载。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from web_infra.logging import get_logger

logger = get_logger("utils.pdf_renderer")


class PdfRenderer:
    """PDF 渲染器：渲染 URL 或 HTML 返回 PDF 字节流"""

    def __init__(
        self,
        timeout_seconds: float = 60,
        ignore_https_errors: bool = True,
        login_script_factory: Callable[[], str] | None = None,
        headless: bool = True,
    ) -> None:
        """初始化渲染器。

        :param timeout_seconds: 页面加载超时（秒，默认 60）
        :param ignore_https_errors: 是否忽略 HTTPS 证书错误（兼容 IP + 自签名证书）
        :param login_script_factory: 登录态注入脚本工厂（返回 JS 字符串，渲染前注入）
        :param headless: 无头模式（默认 True）
        """
        self._timeout_seconds = timeout_seconds
        self._ignore_https_errors = ignore_https_errors
        self._login_script_factory = login_script_factory
        self._headless = headless
        self._playwright: Any = None
        self._browser: Any = None
        self._lock = asyncio.Lock()

    async def render_url(self, url: str, **kwargs: Any) -> bytes:
        """渲染 URL 页面导出 PDF。

        :param url: 页面地址
        :return: PDF 字节流
        """
        return await self._render(target=url, is_url=True, **kwargs)

    async def render_html(self, html: str, **kwargs: Any) -> bytes:
        """渲染 HTML 内容导出 PDF。

        :param html: HTML 源码
        :return: PDF 字节流
        """
        return await self._render(target=html, is_url=False, **kwargs)

    async def close(self) -> None:
        """关闭浏览器与 Playwright 驱动（应用停机时调用）"""
        async with self._lock:
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception as e:  # 关闭失败仅记录日志
                    logger.warning("pdf_browser_close_failed error=%s", str(e))
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

    # ------------------------------------------------------------------
    # 内部：浏览器生命周期与渲染
    # ------------------------------------------------------------------

    async def _ensure_browser(self) -> Any:
        """获取浏览器单例（懒加载，asyncio.Lock 防并发重复启动）"""
        if self._browser is not None:
            return self._browser
        async with self._lock:
            if self._browser is not None:
                return self._browser
            try:
                from playwright.async_api import async_playwright  # type: ignore[reportMissingImports]  # 可选依赖
            except ImportError as e:  # playwright 为可选依赖，未安装时给出安装指引
                raise ImportError("playwright 未安装，请执行 pip install -e \".[pdf]\" 后重试") from e
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,
                ignore_https_errors=self._ignore_https_errors,
            )
            logger.info("pdf_browser_started")
            return self._browser

    async def _render(self, target: str, is_url: bool, timeout_seconds: float | None = None) -> bytes:
        """渲染目标（URL 或 HTML）为 PDF 字节流"""
        browser = await self._ensure_browser()
        page = await browser.new_page()
        try:
            if self._login_script_factory is not None:
                await page.add_init_script(self._login_script_factory())
            timeout_ms = int((timeout_seconds or self._timeout_seconds) * 1000)
            if is_url:
                await page.goto(target, timeout=timeout_ms, wait_until="networkidle")
            else:
                await page.set_content(target)
            return await page.pdf(format="A4")
        finally:
            await page.close()
