"""pytest 配置：把 backend 根目录加入导入路径，并注册 e2e 标记。"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def pytest_configure(config: object) -> None:
    config.addinivalue_line("markers", "e2e: 真实浏览器自动化与起服务的端到端用例")
