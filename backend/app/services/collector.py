"""采集引擎业务规则：状态流转、字段校验与筛选口径都收在这里。

状态语义（按任务生命周期排列）：
- 草稿：登记后尚未提交，不能直接进入运行或归档；
- 待启动：已提交并入队，等待调度执行；
- 运行中：引擎正在采集，只有运行中的任务允许暂停；
- 已停用：被手动暂停的任务，只有它允许恢复；
- 已完成：归档后的终态，任务已结束，禁止恢复或再做任何流转。

允许的状态转移（后端唯一校验入口，路由层不做业务判断）：

| 动作     | 源状态         | 目标状态 | 理由 |
| -------- | -------------- | -------- | ---- |
| 提交启动 | 草稿           | 待启动   | 草稿先入队等待调度，不允许跳过排队直接运行 |
| 提交启动 | 待启动         | 运行中   | 已入队任务再次提交即视为正式启动执行 |
| 暂停采集 | 运行中         | 已停用   | 只有正在采集的任务才能暂停（旧实现把暂停映射成运行中，方向倒置） |
| 恢复采集 | 已停用         | 运行中   | 只有暂停态可恢复（旧实现把恢复映射成已停用，方向倒置）；已完成任务已结束，禁止恢复 |
| 归档任务 | 待启动/运行中/已停用 | 已完成 | 仅已提交过的任务可归档结束；未提交的草稿不能直接归档 |
"""
from __future__ import annotations

import threading
from typing import Any

from app.store import store

MODULE = "collector"
REQUIRED_FIELDS = ["任务编号", "目标网址", "HTTP方法"]
STATUS_ORDER = ["草稿", "待启动", "运行中", "已停用", "已完成"]
TERMINAL_STATUSES = ["已完成"]

# 动作 -> 允许的「源状态: 目标状态」转移表；不在表里的（源状态, 动作）组合一律拒绝。
ALLOWED_TRANSITIONS: dict[str, dict[str, str]] = {
    "提交启动": {"草稿": "待启动", "待启动": "运行中"},
    "暂停采集": {"运行中": "已停用"},
    "恢复采集": {"已停用": "运行中"},
    "归档任务": {"待启动": "已完成", "运行中": "已完成", "已停用": "已完成"},
}

# 转移锁：保证「检查当前状态 -> 写入新状态」整体原子，避免并发提交穿透校验。
_transition_lock = threading.Lock()


class CollectorService:
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
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
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
                return None, f"采集任务 {entry_id} 不存在或已归档"
            if action not in ALLOWED_TRANSITIONS:
                allowed = "、".join(ALLOWED_TRANSITIONS)
                return None, f"动作「{action}」不属于采集引擎可执行范围，允许的动作：{allowed}"

            current = str(entry.get("status") or "")
            if current in TERMINAL_STATUSES:
                if action == "恢复采集":
                    return None, f"采集任务已处于「{current}」终态，任务已结束，不能恢复采集"
                return None, f"采集任务已处于「{current}」终态，不能再执行「{action}」"

            transitions = ALLOWED_TRANSITIONS[action]
            if current not in transitions:
                allowed_states = "、".join(transitions)
                return None, (
                    f"采集任务当前状态为「{current}」，不允许「{action}」；"
                    f"该动作仅适用于状态：{allowed_states}"
                )

            target = transitions[current]
            entry["status"] = target
            entry["pending"] = target not in TERMINAL_STATUSES
            # 暂停态需要人工介入，标记异常；恢复或归档后清除该标记。
            entry["abnormal"] = target == "已停用"
            return entry, f"采集任务已{action}：{current} → {target}"
