"""
容量评估 CLI 模块入口（python -m web_infra.capabilities.capacity）

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 支持 `python -m web_infra.capabilities.capacity [--json] [--remote]`
              直接运行 CLI（§7.3），委托 cli.main 处理参数并返回进程退出码。
"""
import sys

from web_infra.capabilities.capacity.cli import main

if __name__ == "__main__":
    sys.exit(main())
