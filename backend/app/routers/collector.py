"""采集引擎接口：维护采集任务，覆盖提交启动、暂停采集、恢复采集、归档任务等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.actions import ActionOutcome, idempotency, resolve_action
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.collector import MODULE, CollectorService

router = APIRouter(prefix="/api/collector", tags=["采集引擎"])

service = CollectorService()

LIST_FIELDS = ["任务编号", "目标网址", "HTTP方法", "请求头部", "并发线程", "超时秒数", "代理地址", "字符编码"]
STATUSES = ["草稿", "待启动", "运行中", "已停用", "已完成"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    status: str | None = Query(default=None, description="草稿、待启动、运行中、已停用、已完成"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按任务编号与状态过滤采集引擎列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条采集任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"采集任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条采集任务，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="采集任务已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条采集任务执行动作。

    同时兼容顶层 ``action``（新协议）与 ``values.action``（旧协议）；两处动作
    冲突、动作缺失或状态机拒绝都返回可读原因，由前端按 ``ok`` 字段判断成败。
    带 ``token`` 的重复/并发提交只执行一次，并回传同一份最终结果。
    """
    action, error = resolve_action(payload)
    if error is not None:
        return ActionResult(ok=False, message=error, token=(payload.token or None))

    def execute() -> ActionOutcome:
        entry, message = service.run_action(entry_id, action)
        return entry is not None, entry, message

    token = (payload.token or "").strip()
    if not token:
        # 兼容不带幂等令牌的旧调用方：直接执行，不做去重。
        entry, message = execute()
        return ActionResult(ok=entry is not None, message=message, entry=entry)

    result, _duplicate, conflict = idempotency.execute(
        module=MODULE, entry_id=entry_id, token=token, action=action, func=execute
    )
    if conflict:
        raise HTTPException(
            status_code=409,
            detail="同一操作令牌已用于其他动作，拒绝复用令牌；请使用新的操作令牌重新提交",
        )
    return ActionResult(**result)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出采集引擎清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "collector", "total": total, "items": items}
