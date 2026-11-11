"""定时调度接口回归：草稿先校验再启用、禁止跳级、动作协议兼容与幂等。"""
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


def test_legacy_values_action_supported(client: TestClient) -> None:
    body = client.post(
        "/api/scheduler/1/actions",
        json={"values": {"action": "提交校验"}, "token": "legacy-s"},
    ).json()
    assert body["ok"] is True
    assert body["entry"]["status"] == "待校验"


def test_conflicting_action_inputs_rejected(client: TestClient) -> None:
    body = client.post(
        "/api/scheduler/1/actions",
        json={"action": "启用计划", "values": {"action": "停用计划"}, "token": "conflict-s"},
    ).json()
    assert body["ok"] is False
    assert "动作冲突" in body["message"]
    assert client.get("/api/scheduler/1").json()["status"] == "草稿"


def test_draft_must_validate_before_enable_no_level_skipping(client: TestClient) -> None:
    body = client.post(
        "/api/scheduler/1/actions", json={"action": "启用计划", "token": "skip-1"}
    ).json()
    assert body["ok"] is False
    assert "先「提交校验」" in body["message"]
    assert client.get("/api/scheduler/1").json()["status"] == "草稿"


def test_full_schedule_lifecycle(client: TestClient) -> None:
    plan_id = 1
    for token, action, expected in [
        ("life-1", "提交校验", "待校验"),
        ("life-2", "启用计划", "已启用"),
        ("life-3", "停用计划", "已停用"),
        ("life-4", "启用计划", "已启用"),
    ]:
        body = client.post(
            f"/api/scheduler/{plan_id}/actions",
            json={"action": action, "token": token},
        ).json()
        assert body["ok"] is True, body["message"]
        assert body["entry"]["status"] == expected


def test_cannot_disable_plan_that_is_not_enabled(client: TestClient) -> None:
    # id=2 处于待校验，停用必须拒绝。
    body = client.post(
        "/api/scheduler/2/actions", json={"action": "停用计划", "token": "disable-2"}
    ).json()
    assert body["ok"] is False
    assert "已启用" in body["message"]


def test_illegal_action_rejected(client: TestClient) -> None:
    body = client.post(
        "/api/scheduler/1/actions", json={"action": "删除计划", "token": "illegal-s"}
    ).json()
    assert body["ok"] is False
    assert "不属于定时调度可执行范围" in body["message"]


def test_same_token_duplicate_confirms_final_state(client: TestClient) -> None:
    payload = {"action": "提交校验", "token": "dup-s"}
    first = client.post("/api/scheduler/1/actions", json=payload).json()
    second = client.post("/api/scheduler/1/actions", json=payload).json()
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["entry"]["status"] == "待校验"


def test_concurrent_same_token_executes_once(client: TestClient) -> None:
    def fire(_: int) -> dict:
        return client.post(
            "/api/scheduler/3/actions",
            json={"action": "停用计划", "token": "parallel-s"},
        ).json()

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(fire, range(12)))

    assert sum(1 for item in results if item["duplicate"] is False) == 1
    assert all(item["ok"] is True for item in results)
    assert client.get("/api/scheduler/3").json()["status"] == "已停用"
