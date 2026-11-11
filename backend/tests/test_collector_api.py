"""采集引擎接口回归：动作双协议、冲突拒绝、状态机、终态保护与幂等。

覆盖需求点：
- 旧协议 values.action 仍可用；新协议顶层 action 可用；
- 两种输入同时出现且冲突必须拒绝，不能挑一个执行；
- 非法动作与非法转移由后端统一校验并给出原因；
- 已完成任务不得恢复；
- 同一操作令牌重复/并发只执行一次，重复响应能确认最终结果。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.actions import idempotency
from app.main import app
from app.store import store


@pytest.fixture()
def client() -> TestClient:
    store.reset()
    idempotency.reset()
    return TestClient(app)


def test_new_protocol_top_level_action_works(client: TestClient) -> None:
    response = client.post(
        "/api/collector/1/actions",
        json={"action": "提交启动", "token": "new-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["entry"]["status"] == "待启动"
    assert body["duplicate"] is False


def test_legacy_protocol_values_action_still_supported(client: TestClient) -> None:
    """已使用 values.action 的旧调用方不能被新协议改坏。"""
    response = client.post(
        "/api/collector/1/actions",
        json={"values": {"action": "提交启动"}, "token": "legacy-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["entry"]["status"] == "待启动"


def test_duplicate_action_inputs_with_same_value_are_accepted(client: TestClient) -> None:
    response = client.post(
        "/api/collector/1/actions",
        json={"action": "提交启动", "values": {"action": "提交启动"}, "token": "same-1"},
    )
    assert response.json()["ok"] is True
    assert response.json()["entry"]["status"] == "待启动"


def test_conflicting_action_inputs_are_rejected_not_guessed(client: TestClient) -> None:
    response = client.post(
        "/api/collector/1/actions",
        json={"action": "暂停采集", "values": {"action": "恢复采集"}, "token": "conflict-1"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is False
    assert "动作冲突" in body["message"]
    # 拒绝后状态必须保持原样，绝不允许悄悄执行其中一个动作。
    assert client.get("/api/collector/1").json()["status"] == "草稿"


def test_missing_action_is_rejected(client: TestClient) -> None:
    response = client.post("/api/collector/1/actions", json={"token": "no-action"})
    body = response.json()
    assert body["ok"] is False
    assert "缺少动作参数" in body["message"]


def test_illegal_action_name_rejected_with_reason(client: TestClient) -> None:
    response = client.post(
        "/api/collector/3/actions",
        json={"action": "删除任务", "token": "bad-action"},
    )
    body = response.json()
    assert body["ok"] is False
    assert "不属于采集引擎可执行范围" in body["message"]
    assert client.get("/api/collector/3").json()["status"] == "运行中"


def test_full_valid_lifecycle_and_corrected_pause_resume_direction(client: TestClient) -> None:
    """暂停 运行中→已停用、恢复 已停用→运行中，修正旧实现的映射倒置。"""
    # 初始为运行中的 id=3
    paused = client.post(
        "/api/collector/3/actions", json={"action": "暂停采集", "token": "lc-1"}
    ).json()
    assert paused["ok"] is True
    assert paused["entry"]["status"] == "已停用"
    assert paused["entry"]["abnormal"] is True

    resumed = client.post(
        "/api/collector/3/actions", json={"action": "恢复采集", "token": "lc-2"}
    ).json()
    assert resumed["ok"] is True
    assert resumed["entry"]["status"] == "运行中"
    assert resumed["entry"]["abnormal"] is False


def test_pause_only_allowed_when_running(client: TestClient) -> None:
    # id=1 是草稿，暂停必须被拒。
    body = client.post(
        "/api/collector/1/actions", json={"action": "暂停采集", "token": "pause-draft"}
    ).json()
    assert body["ok"] is False
    assert "运行中" in body["message"]
    assert client.get("/api/collector/1").json()["status"] == "草稿"


def test_resume_only_allowed_when_suspended(client: TestClient) -> None:
    # id=3 运行中直接恢复，必须被拒。
    body = client.post(
        "/api/collector/3/actions", json={"action": "恢复采集", "token": "resume-running"}
    ).json()
    assert body["ok"] is False
    assert "已停用" in body["message"]


def test_completed_task_can_never_resume(client: TestClient) -> None:
    client.post("/api/collector/2/actions", json={"action": "提交启动", "token": "fin-1"})
    archived = client.post(
        "/api/collector/2/actions", json={"action": "归档任务", "token": "fin-2"}
    ).json()
    assert archived["entry"]["status"] == "已完成"

    body = client.post(
        "/api/collector/2/actions", json={"action": "恢复采集", "token": "fin-3"}
    ).json()
    assert body["ok"] is False
    assert "终态" in body["message"] and "不能恢复" in body["message"]
    assert client.get("/api/collector/2").json()["status"] == "已完成"


def test_draft_cannot_be_archived_directly(client: TestClient) -> None:
    body = client.post(
        "/api/collector/1/actions", json={"action": "归档任务", "token": "archive-draft"}
    ).json()
    assert body["ok"] is False
    assert client.get("/api/collector/1").json()["status"] == "草稿"


def test_same_token_duplicate_executes_once_and_confirms_result(client: TestClient) -> None:
    first = client.post(
        "/api/collector/1/actions",
        json={"action": "提交启动", "token": "dup-token"},
    ).json()
    second = client.post(
        "/api/collector/1/actions",
        json={"action": "提交启动", "token": "dup-token"},
    ).json()
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    # 重复请求回显同一份最终结果，界面可据此确认而不是再执行一次。
    assert second["ok"] is first["ok"]
    assert second["entry"]["status"] == first["entry"]["status"] == "待启动"


def test_rejected_result_is_replayed_for_duplicate_token(client: TestClient) -> None:
    payload = {"action": "暂停采集", "token": "reject-token"}  # 草稿上暂停，必拒
    first = client.post("/api/collector/1/actions", json=payload).json()
    second = client.post("/api/collector/1/actions", json=payload).json()
    assert first["ok"] is False and second["ok"] is False
    assert second["duplicate"] is True
    assert second["message"] == first["message"]


def test_concurrent_same_token_runs_exactly_once(client: TestClient) -> None:
    def fire(_: int) -> dict:
        return client.post(
            "/api/collector/1/actions",
            json={"action": "提交启动", "token": "parallel-token"},
        ).json()

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(fire, range(12)))

    assert sum(1 for item in results if item["duplicate"] is False) == 1
    assert sum(1 for item in results if item["duplicate"] is True) == 11
    assert all(item["ok"] is True for item in results)
    assert client.get("/api/collector/1").json()["status"] == "待启动"


def test_same_token_with_different_action_is_conflict_409(client: TestClient) -> None:
    first = client.post(
        "/api/collector/1/actions", json={"action": "提交启动", "token": "reuse"}
    )
    assert first.json()["ok"] is True
    conflict = client.post(
        "/api/collector/1/actions", json={"action": "归档任务", "token": "reuse"}
    )
    assert conflict.status_code == 409
    assert "令牌" in conflict.json()["detail"]
