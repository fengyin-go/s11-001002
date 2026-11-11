"""动作解析与幂等存储的单元测试，不依赖 HTTP 层。"""
from __future__ import annotations

import threading

from app.actions import IdempotencyStore, resolve_action
from app.schemas import EntryPayload


def test_resolve_top_level_action() -> None:
    action, error = resolve_action(EntryPayload(action="提交启动"))
    assert action == "提交启动"
    assert error is None


def test_resolve_legacy_values_action() -> None:
    action, error = resolve_action(EntryPayload(values={"action": "暂停采集"}))
    assert action == "暂停采集"
    assert error is None


def test_resolve_identical_dual_inputs() -> None:
    action, error = resolve_action(
        EntryPayload(action="归档任务", values={"action": "归档任务"})
    )
    assert action == "归档任务"
    assert error is None


def test_resolve_conflicting_dual_inputs() -> None:
    action, error = resolve_action(
        EntryPayload(action="暂停采集", values={"action": "恢复采集"})
    )
    assert action == ""
    assert error is not None and "动作冲突" in error


def test_resolve_missing_action() -> None:
    action, error = resolve_action(EntryPayload())
    assert action == ""
    assert error is not None and "缺少动作参数" in error


def test_idempotency_store_replays_cached_outcome() -> None:
    store = IdempotencyStore()
    calls = 0

    def func() -> tuple[bool, dict | None, str]:
        nonlocal calls
        calls += 1
        return True, {"id": 1, "status": "运行中"}, "ok"

    first, dup1, conflict1 = store.execute(
        module="collector", entry_id=1, token="t", action="暂停采集", func=func
    )
    second, dup2, conflict2 = store.execute(
        module="collector", entry_id=1, token="t", action="暂停采集", func=func
    )
    assert calls == 1
    assert dup1 is False and dup2 is True
    assert conflict1 is False and conflict2 is False
    assert first["entry"] == second["entry"] == {"id": 1, "status": "运行中"}
    assert second["duplicate"] is True


def test_idempotency_store_flags_token_action_conflict() -> None:
    store = IdempotencyStore()
    store.execute(
        module="scheduler",
        entry_id=2,
        token="t",
        action="启用计划",
        func=lambda: (True, {"id": 2}, "done"),
    )
    _result, duplicate, conflict = store.execute(
        module="scheduler",
        entry_id=2,
        token="t",
        action="停用计划",
        func=lambda: (True, {}, "should not run"),
    )
    assert conflict is True
    assert duplicate is False


def test_idempotency_store_serializes_concurrent_calls() -> None:
    store = IdempotencyStore()
    calls = 0
    barrier = threading.Barrier(8)

    def func() -> tuple[bool, dict | None, str]:
        nonlocal calls
        calls += 1
        return True, {"id": 9}, "once"

    outcomes: list[tuple[bool, bool]] = []

    def worker() -> None:
        barrier.wait()
        _result, duplicate, conflict = store.execute(
            module="collector", entry_id=9, token="same", action="归档任务", func=func
        )
        outcomes.append((duplicate, conflict))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert calls == 1
    assert sum(1 for duplicate, _ in outcomes if not duplicate) == 1
    assert all(not conflict for _, conflict in outcomes)
