"""
测试包标记

@Author: 花海
@Date: 2026/08/17
@Description: 将 tests 声明为 Python 包，保证 CI 中 `pytest`（非 python -m pytest）运行时
              `from tests.test_xxx import ...` 的跨测试文件导入可用（pytest prepend 模式
              以包含 __init__.py 的包根目录作为 sys.path 插入点）。
"""
