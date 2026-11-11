"""智能采集调度平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.actions import idempotency
from app.config import settings
from app.routers import ROUTERS
from app.store import store

app = FastAPI(title="智能采集调度平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in ROUTERS:
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names())}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片。"""
    return store.overview()


@app.post("/api/testing/reset")
def testing_reset() -> dict[str, object]:
    """仅供端到端测试使用的数据重置钩子；未显式开启时直接拒绝，避免线上被误调。"""
    if os.environ.get("ENABLE_TEST_RESET") != "1":
        raise HTTPException(status_code=404, detail="Not Found")
    store.reset()
    idempotency.reset()
    return {"ok": True}
