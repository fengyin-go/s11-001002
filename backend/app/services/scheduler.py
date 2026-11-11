"""定时调度业务规则：状态流转、字段校验与筛选口径都收在这里。

状态语义（按计划上线顺序排列）：
- 草稿：登记后尚未提交校验，任何启用动作都必须先经过校验，禁止跳级；
- 待校验：已提交校验并通过，等待人工启用；
- 已启用：计划正在参与定时调度；
- 已停用：被手动停用，停用后可以重新启用。

允许的状态转移（后端唯一校验入口，路由层不做业务判断）：

| 动作     | 源状态 | 目标状态 | 理由 |
| -------- | ------ | -------- | ---- |
| 提交校验 | 草稿   | 待校验   | 草稿必须先校验通过才能启用，杜绝未校验直接上线 |
| 启用计划 | 待校验 | 已启用   | 只有校验通过的计划允许启用，草稿不得跳级 |
| 启用计划 | 已停用 | 已启用   | 停用后的计划可以重新启用 |
| 停用计划 | 已启用 | 已停用   | 只有正在生效的计划允许停用 |
"""
from __future__ import annotations

import threading
from typing import Any

from app.store import store

MODULE = "scheduler"
REQUIRED_FIELDS = ["计划编号", "Cron表达式", "关联任务"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]

# 动作 -> 允许的「源状态: 目标状态」转移表；不在表里的（源状态, 动作）组合一律拒绝。
ALLOWED_TRANSITIONS: dict[str, dict[str, str]] = {
    "提交校验": {"草稿": "待校验"},
    "启用计划": {"待校验": "已启用", "已停用": "已启用"},
    "停用计划": {"已启用": "已停用"},
}

# 转移锁：保证「检查当前状态 -> 写入新状态」整体原子，避免并发提交穿透校验。
_transition_lock = threading.Lock()


class SchedulerService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("计划编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        with _transition_lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"调度计划 {entry_id} 不存在或已归档"
            if action not in ALLOWED_TRANSITIONS:
                allowed = "、".join(ALLOWED_TRANSITIONS)
                return None, f"动作「{action}」不属于定时调度可执行范围，允许的动作：{allowed}"

            current = str(entry.get("status") or "")
            transitions = ALLOWED_TRANSITIONS[action]
            if current not in transitions:
                allowed_states = "、".join(transitions)
                if action == "启用计划" and current == "草稿":
                    reason = "草稿计划必须先「提交校验」通过后才能启用，禁止跳过校验直接上线"
                else:
                    reason = (
                        f"该动作仅适用于状态：{allowed_states}"
                    )
                return None, f"调度计划当前状态为「{current}」，不允许「{action}」；{reason}"

            target = transitions[current]
            entry["status"] = target
            # 停用与待校验都需要后续人工处理；已启用进入正常调度，不再待处理。
            entry["pending"] = target != "已启用"
            entry["abnormal"] = target == "已停用"
            return entry, f"调度计划已{action}：{current} → {target}"
