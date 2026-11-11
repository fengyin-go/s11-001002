"""定时调度接口：维护调度计划，覆盖提交校验、启用计划、停用计划等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.actions import ActionOutcome, idempotency, resolve_action
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.scheduler import MODULE, SchedulerService

router = APIRouter(prefix="/api/scheduler", tags=["定时调度"])

service = SchedulerService()

LIST_FIELDS = ["计划编号", "Cron表达式", "关联任务", "时区设置", "最大执行时长", "并发上限", "错过补偿策略", "有效日期范围"]
STATUSES = ["草稿", "待校验", "已启用", "已停用"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按计划编号检索"),
    status: str | None = Query(default=None, description="草稿、待校验、已启用、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按计划编号与状态过滤定时调度列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条调度计划明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"调度计划 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条调度计划，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="调度计划已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条调度计划执行动作。

    同时兼容顶层 ``action``（新协议）与 ``values.action``（旧协议）；两处动作
    冲突、动作缺失或状态机拒绝（含草稿未校验直接启用的跳级请求）都返回可读原因，
    由前端按 ``ok`` 字段判断成败。带 ``token`` 的重复/并发提交只执行一次。
    """
    action, error = resolve_action(payload)
    if error is not None:
        return ActionResult(ok=False, message=error, token=(payload.token or None))

    def execute() -> ActionOutcome:
        entry, message = service.run_action(entry_id, action)
        return entry is not None, entry, message

    token = (payload.token or "").strip()
    if not token:
        entry, message = service.run_action(entry_id, action)
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
    """导出定时调度清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "scheduler", "total": total, "items": items}
