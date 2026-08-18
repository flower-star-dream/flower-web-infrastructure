"""
PDF 渲染导出组件单元测试

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 用 Fake 浏览器验证 URL/HTML 渲染路径、登录态注入与资源关闭（playwright 为可选依赖，不真实启动）。
"""
import pytest

from web_infra.infra.utils import PdfRenderer


class _FakePage:
    """模拟 playwright 页面：记录调用并返回假 PDF"""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.goto_url: str | None = None
        self.set_content_html: str | None = None
        self.scripts: list[str] = []

    async def add_init_script(self, script: str) -> None:
        self.scripts.append(script)
        self.calls.append("add_init_script")

    async def goto(self, url: str, timeout: int, wait_until: str) -> None:
        self.goto_url = url
        self.calls.append("goto")

    async def set_content(self, html: str) -> None:
        self.set_content_html = html
        self.calls.append("set_content")

    async def pdf(self, format: str) -> bytes:
        self.calls.append("pdf")
        return b"%PDF-1.4 fake"

    async def close(self) -> None:
        self.calls.append("close")


class _FakeBrowser:
    """模拟 playwright 浏览器：new_page 返回 FakePage"""

    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.closed = False

    async def new_page(self) -> _FakePage:
        return self._page

    async def close(self) -> None:
        self.closed = True


def _make_renderer(**kwargs) -> tuple[PdfRenderer, _FakePage, _FakeBrowser]:
    """构造渲染器并注入 Fake 浏览器"""
    renderer = PdfRenderer(**kwargs)
    page = _FakePage()
    browser = _FakeBrowser(page)

    async def _fake_ensure_browser():
        return browser

    renderer._ensure_browser = _fake_ensure_browser  # type: ignore[method-assign]
    return renderer, page, browser


@pytest.mark.asyncio
async def test_render_url():
    """渲染 URL：goto + pdf，返回 PDF 字节"""
    renderer, page, _ = _make_renderer()
    result = await renderer.render_url("http://localhost:5173/report")
    assert result == b"%PDF-1.4 fake"
    assert page.goto_url == "http://localhost:5173/report"
    assert "goto" in page.calls and "pdf" in page.calls and "close" in page.calls


@pytest.mark.asyncio
async def test_render_html():
    """渲染 HTML：set_content + pdf"""
    renderer, page, _ = _make_renderer()
    result = await renderer.render_html("<html><body>报告</body></html>")
    assert result == b"%PDF-1.4 fake"
    assert "报告" in (page.set_content_html or "")
    assert "goto" not in page.calls


@pytest.mark.asyncio
async def test_login_script_injected():
    """配置登录态注入工厂时渲染前注入脚本"""
    renderer, page, _ = _make_renderer(login_script_factory=lambda: "localStorage.setItem('token','x')")
    await renderer.render_url("http://localhost:5173/report")
    assert "localStorage.setItem('token','x')" in page.scripts


@pytest.mark.asyncio
async def test_no_login_script_by_default():
    """未配置登录态工厂时不注入脚本"""
    renderer, page, _ = _make_renderer()
    await renderer.render_html("<html/>")
    assert page.scripts == []


@pytest.mark.asyncio
async def test_close_releases_browser():
    """close 关闭浏览器并置空引用"""
    renderer, _, browser = _make_renderer()
    renderer._browser = browser

    class _FakePlaywright:
        stopped = False

        async def stop(self) -> None:
            self.stopped = True

    playwright = _FakePlaywright()
    renderer._playwright = playwright
    await renderer.close()
    assert browser.closed is True
    assert renderer._browser is None
    assert renderer._playwright is None
    assert playwright.stopped is True


@pytest.mark.asyncio
async def test_render_without_playwright_raises_import_error():
    """未安装 playwright 时抛 ImportError（带安装指引）"""
    renderer = PdfRenderer()
    with pytest.raises(ImportError, match=r"\[pdf\]"):
        await renderer.render_url("http://localhost/x")
