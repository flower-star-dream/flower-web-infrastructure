"""从 TestPyPI 安装并验证 flower-web-infrastructure 的本地验证脚本

@Author: 花海
@Date: 2026/08/18 10:30
@Description: 模拟用户从 TestPyPI 安装包的真实行为并验证核心/支付能力：
              创建独立虚拟环境（默认 <项目根>/.venv-testpypi，存在则复用）
              → 从 TestPyPI 安装（包本体走 TestPyPI，依赖走官方 PyPI，
                两步分开：TestPyPI 上存在抢注同名包，合并索引会装到损坏依赖，
                详见 install_package）
              → 在目标环境中执行验证代码：
                web_infra 版本 / create_app 可创建应用（默认加载随包 application.default.yml）/
                支付模块（注册表 + 内存网关 prepay 冒烟 + 微信渠道 provider 可导入）。
              --local 时改从本地 dist/ 安装（发布前自测，无需等待 TestPyPI 发布）。

用法：
    python scripts/verify_testpypi_install.py                 # 从 TestPyPI 安装并验证
    python scripts/verify_testpypi_install.py --local         # 从本地 dist/ 安装并验证（发布前自测）
    python scripts/verify_testpypi_install.py --skip-install  # 复用已有环境，仅执行验证代码
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENV = PROJECT_ROOT / ".venv-testpypi"

TESTPYPI_INDEX = "https://test.pypi.org/simple/"
PYPI_INDEX = "https://pypi.org/simple/"
PACKAGE_NAME = "flower-web-infrastructure"

# 在目标验证环境执行的验证代码（python -c 运行；任何断言失败/异常 → 非 0 退出码）
_VERIFY_CODE = r"""
import asyncio
from decimal import Decimal
from pathlib import Path

import web_infra
print(f"[verify] web_infra 版本: {web_infra.__version__}")

# 1) 核心：create_app 可创建应用（默认加载随包 application.default.yml）
from web_infra import create_app
app = create_app()
print(f"[verify] create_app OK -> {type(app).__name__}")

# 2) 默认配置文件随包分发（pip 安装后位于 site-packages 内）
config_path = Path(web_infra.__file__).parent / "infra" / "config" / "application.default.yml"
assert config_path.is_file(), f"缺少随包配置文件: {config_path}"
print(f"[verify] application.default.yml 已随包: {config_path}")

# 3) 支付模块：导入 + 注册表 + 内存网关 prepay 冒烟（支付为可选能力，须显式子模块导入）
from web_infra.capabilities.payment import (
    InMemoryPaymentGateway,
    PaymentGatewayRegistry,
    PaymentPrepayRequest,
    PaymentScene,
)
gateway = InMemoryPaymentGateway()
PaymentGatewayRegistry.register("in_memory", gateway)
assert PaymentGatewayRegistry.get("in_memory") is gateway, "注册表 get 应返回已注册网关"
assert "in_memory" in PaymentGatewayRegistry.registered_names(), "注册表应含 in_memory 渠道"


async def smoke() -> str:
    resp = await gateway.prepay(PaymentPrepayRequest(
        out_trade_no="VERIFY2026081800001",
        description="TestPyPI 验证订单",
        total_amount=Decimal("1.00"),
        scene=PaymentScene.NATIVE,
    ))
    assert resp.code_url, "NATIVE 下单应返回 code_url"
    order = await gateway.query_order("VERIFY2026081800001")
    assert order is not None and order.out_trade_no == "VERIFY2026081800001", "查单应命中下单订单"
    return resp.code_url


code_url = asyncio.run(smoke())
print(f"[verify] 支付 prepay + query_order OK -> {code_url}")

# 4) 微信渠道 provider 可导入（打包完整性，依赖为核心 cryptography，无需配置即可导入；
#    provider 包 __init__ 无导出，按具体模块路径引用）
from web_infra.capabilities.payment.provider.wechat.wechat_pay_provider import WeChatPayProvider
from web_infra.capabilities.payment.provider.wechat.wechat_signer import WeChatSigner
print(f"[verify] 微信渠道 provider 导入 OK -> {WeChatPayProvider.__name__} / {WeChatSigner.__name__}")

print("[verify] 全部验证通过")
"""


def _python_of(venv_dir: Path) -> Path:
    """返回虚拟环境内 Python 解释器路径（Windows 为 Scripts/python.exe）"""
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_venv(venv_dir: Path) -> None:
    """创建独立虚拟环境（已存在则复用，不重复安装）。

    :param venv_dir: 虚拟环境目录
    """
    if not venv_dir.exists():
        print(f"[setup] 创建虚拟环境: {venv_dir}")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    else:
        print(f"[setup] 复用虚拟环境: {venv_dir}")


def _load_core_dependencies() -> list[str]:
    """从 pyproject.toml 解析 [project].dependencies 核心依赖列表（正则解析，兼容 Python 3.10，无需 tomllib）。

    :return: 依赖规格列表（如 ["fastapi>=0.110", ...]）
    :raises SystemExit: 无法解析 dependencies 段时
    """
    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"^dependencies = \[(.*?)^\]", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise SystemExit("[install] 无法解析 pyproject.toml 的 [project].dependencies")
    dependencies: list[str] = []
    for line in match.group(1).splitlines():
        line = line.strip().rstrip(",")
        if line.startswith('"') and line.endswith('"'):
            dependencies.append(line[1:-1])
    return dependencies


def install_package(python: Path, source: str) -> None:
    """在验证环境中安装目标包。

    TestPyPI 依赖解析的坑（实测踩中）：TestPyPI 上存在抢注的同名依赖包
    （如损坏的 FASTAPI-1.0.tar.gz），用 --index-url testpypi + --extra-index-url pypi
    合并索引时，pip 会选中 TestPyPI 上的损坏候选导致安装失败。因此分两步：
    1) 核心依赖（pyproject [project].dependencies）先走官方 PyPI；
    2) 包本体再 --no-deps 从 TestPyPI 拉取（依赖已在环境中，无需二次解析）。

    :param python: 验证环境解释器
    :param source: testpypi（依赖官方 PyPI + 本体 TestPyPI）/ local（本地 dist/）
    """
    if source == "testpypi":
        dependencies = _load_core_dependencies()
        print(f"[install] 1/2 官方 PyPI 安装核心依赖（{len(dependencies)} 项）...")
        subprocess.run(
            [str(python), "-m", "pip", "install", "--index-url", PYPI_INDEX, *dependencies],
            check=True,
        )
        print("[install] 2/2 TestPyPI 安装包本体（--no-deps，避免索引串扰）...")
        subprocess.run(
            [str(python), "-m", "pip", "install", "--index-url", TESTPYPI_INDEX, "--no-deps", PACKAGE_NAME],
            check=True,
        )
    else:
        dist_dir = PROJECT_ROOT / "dist"
        if not any(dist_dir.glob("*.whl")) and not any(dist_dir.glob("*.tar.gz")):
            raise SystemExit(f"[install] 本地 dist/ 无构建产物，请先执行 python -m build 生成发行包: {dist_dir}")
        args = [
            str(python), "-m", "pip", "install",
            "--find-links", str(dist_dir),       # 包本体优先从本地 dist/ 取
            "--index-url", PYPI_INDEX,           # 依赖照常从官方 PyPI 解析
            PACKAGE_NAME,
        ]
        subprocess.run(args, check=True)
    print(f"[install] 安装来源: {source}")


def run_verify(python: Path) -> None:
    """在验证环境中执行验证代码（导入/断言失败即退出非 0）。

    :param python: 验证环境解释器
    """
    print("[verify] 执行验证代码（版本 / create_app / 配置文件 / 支付模块）...")
    subprocess.run([str(python), "-c", _VERIFY_CODE], check=True)


def main() -> int:
    """入口：解析参数 → 准备虚拟环境 → 安装 → 验证。

    :return: 退出码（安装或验证失败时非 0，便于 CI/本地脚本联动）
    """
    parser = argparse.ArgumentParser(description="从 TestPyPI（或本地 dist/）安装并验证 flower-web-infrastructure")
    parser.add_argument("--venv", type=Path, default=DEFAULT_VENV, help="虚拟环境目录（默认 <项目根>/.venv-testpypi）")
    parser.add_argument(
        "--local", action="store_true",
        help="从本地 dist/ 安装（--no-index），用于发布前自测；缺省从 TestPyPI 安装",
    )
    parser.add_argument(
        "--skip-install", action="store_true",
        help="跳过安装步骤，仅对已有环境执行验证代码（环境须已装目标包）",
    )
    args = parser.parse_args()

    venv_dir: Path = args.venv
    source = "local" if args.local else "testpypi"

    ensure_venv(venv_dir)
    python = _python_of(venv_dir)

    if args.skip_install:
        if not python.exists():
            raise SystemExit(f"[setup] 指定环境不存在，无法 --skip-install: {venv_dir}")
        print("[install] 跳过安装（--skip-install）")
    else:
        install_package(python, source)

    run_verify(python)
    print("[verify] 验证完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
