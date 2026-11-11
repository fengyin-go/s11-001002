"""真实浏览器端到端回归（Playwright + 起 uvicorn/vite 真服务）。

运行方式（仓库根目录）：
    ENABLE_BROWSER_E2E=1 \
    BROWSER_LIB_ROOT=/tmp/browser-libs/root \
    python3 -m pytest backend/tests/test_browser_e2e.py -m e2e -s

覆盖两页的真实点击与接口复现：
- 旧协议 values.action、新旧协议动作冲突；
- 合法流转成功并刷新出真实状态、非法动作展示后端原因且不假装完成；
- 同一操作令牌重复点击/并发只执行一次；
- 采集引擎暂停/恢复方向、已完成不可恢复；
- 定时调度草稿必须先校验再启用，禁止跳级。
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect, sync_playwright

pytestmark = pytest.mark.e2e

BACKEND_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = BACKEND_ROOT.parent
FRONTEND_ROOT = WORKSPACE_ROOT / "frontend"


def _terminate_group(process: subprocess.Popen) -> None:
    """向整个进程组发终止信号，回收 npm/uvicorn 派生出的子进程。"""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for(url: str, timeout: float = 30.0) -> None:
    import urllib.request

    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - 启动轮询需要兜底
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"服务未就绪：{url}，最后错误：{last_error}")


def _browser_launch_env() -> dict[str, str]:
    env = dict(os.environ)
    lib_root = os.environ.get("BROWSER_LIB_ROOT")
    if lib_root:
        lib_paths = sorted(
            str(path.parent)
            for path in Path(lib_root).rglob("*.so*")
            if path.is_file()
        )
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = ":".join(lib_paths + ([existing] if existing else []))
    return env


@pytest.fixture(scope="module")
def servers():
    if os.environ.get("ENABLE_BROWSER_E2E") != "1":
        pytest.skip("未设置 ENABLE_BROWSER_E2E=1，跳过浏览器端到端用例")

    backend_port = _free_port()
    frontend_port = _free_port()
    backend_env = dict(os.environ, ENABLE_TEST_RESET="1", PYTHONPATH=str(BACKEND_ROOT))
    # start_new_session 让每个服务自成进程组，结束时整组回收，
    # 避免 npm 派生的 vite 子进程在 terminate() 后成为孤儿。
    backend = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(backend_port),
        ],
        cwd=BACKEND_ROOT,
        env=backend_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    frontend = subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", str(frontend_port), "--strictPort"],
        cwd=FRONTEND_ROOT,
        env=dict(os.environ, VITE_PROXY_TARGET=f"http://127.0.0.1:{backend_port}"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        _wait_for(f"http://127.0.0.1:{backend_port}/api/health")
        _wait_for(f"http://127.0.0.1:{frontend_port}/")
        yield {
            "backend": f"http://127.0.0.1:{backend_port}",
            "frontend": f"http://127.0.0.1:{frontend_port}",
        }
    finally:
        _terminate_group(frontend)
        _terminate_group(backend)


@pytest.fixture()
def page(servers):
    import urllib.request

    # 每个用例前把后端内存数据与幂等记录还原到种子状态。
    req = urllib.request.Request(f"{servers['backend']}/api/testing/reset", method="POST")
    with urllib.request.urlopen(req, timeout=5) as response:
        assert response.status == 200

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(env=_browser_launch_env())
        tab = browser.new_page()
        yield tab
        browser.close()


def _row_for(page: Page, code: str):
    return page.locator("tbody tr", has_text=code).first


def _status_of(row) -> str:
    return row.locator("td").nth(-2).inner_text().strip()


def _click_action(row, label: str) -> None:
    row.get_by_role("button", name=label).click()


# ----------------------------- 采集引擎 -----------------------------


def test_collector_valid_click_flow_updates_real_status(page: Page, servers) -> None:
    page.goto(f"{servers['frontend']}/collector")
    expect(page.get_by_role("heading", name="采集引擎管理")).to_be_visible()

    row = _row_for(page, "COLL-0001")  # 种子数据：草稿
    assert _status_of(row) == "草稿"

    _click_action(row, "提交启动")
    expect(page.locator(".success-text")).to_have_text(
        "采集任务已提交启动：草稿 → 待启动"
    )
    # 列表来自后端重新拉取，状态必须真实变化，而不是前端本地改出来的。
    expect(row.locator("td").nth(-2)).to_have_text("待启动")

    _click_action(row, "提交启动")
    expect(page.locator(".success-text")).to_have_text(
        "采集任务已提交启动：待启动 → 运行中"
    )
    expect(row.locator("td").nth(-2)).to_have_text("运行中")

    # 修正后的方向：暂停 运行中 → 已停用；恢复 已停用 → 运行中。
    _click_action(row, "暂停采集")
    expect(row.locator("td").nth(-2)).to_have_text("已停用")
    _click_action(row, "恢复采集")
    expect(row.locator("td").nth(-2)).to_have_text("运行中")


def test_collector_illegal_action_shows_backend_reason(page: Page, servers) -> None:
    page.goto(f"{servers['frontend']}/collector")
    row = _row_for(page, "COLL-0001")  # 草稿
    # 草稿上直接暂停属于非法转移，后端拒绝；界面必须展示原因且状态不变。
    _click_action(row, "暂停采集")
    expect(page.locator(".error-text")).to_contain_text("不允许「暂停采集」")
    expect(row.locator("td").nth(-2)).to_have_text("草稿")


def test_collector_completed_task_cannot_resume(page: Page, servers) -> None:
    import urllib.request

    backend = servers["backend"]
    # 接口复现：把 id=2（待启动）推进到已完成终态。
    def post(body: dict) -> dict:
        req = urllib.request.Request(
            f"{backend}/api/collector/2/actions",
            data=__import__("json").dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return __import__("json").loads(response.read())

    assert post({"action": "提交启动", "token": "e2e-fin-1"})["entry"]["status"] == "运行中"
    assert post({"action": "归档任务", "token": "e2e-fin-2"})["entry"]["status"] == "已完成"

    page.goto(f"{servers['frontend']}/collector")
    row = _row_for(page, "COLL-0002")
    expect(row.locator("td").nth(-2)).to_have_text("已完成")
    _click_action(row, "恢复采集")
    expect(page.locator(".error-text")).to_contain_text("终态")
    expect(page.locator(".error-text")).to_contain_text("不能恢复")
    expect(row.locator("td").nth(-2)).to_have_text("已完成")


def test_collector_legacy_and_conflicting_protocols(page: Page, servers) -> None:
    import json
    import urllib.request

    backend = servers["backend"]

    def post(body: dict) -> dict:
        req = urllib.request.Request(
            f"{backend}/api/collector/1/actions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read())

    # 旧协议仍可用。
    legacy = post({"values": {"action": "提交启动"}, "token": "e2e-legacy"})
    assert legacy["ok"] is True and legacy["entry"]["status"] == "待启动"

    # 先进入应用页面，让浏览器内 fetch 有同源基址并经 vite 代理转发。
    page.goto(f"{servers['frontend']}/collector")
    # 浏览器内复现冲突请求：页面必须能读到后端原因并展示，不能假装完成。
    # 走相对地址经 vite 代理到后端，避免跨端口 CORS 限制。
    conflict = page.evaluate(
        """async (payload) => {
            const res = await fetch('/api/collector/1/actions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            })
            return { status: res.status, body: await res.json() }
        }""",
        {"action": "暂停采集", "values": {"action": "恢复采集"}, "token": "e2e-conflict"},
    )
    assert conflict["status"] == 200
    assert conflict["body"]["ok"] is False
    assert "动作冲突" in conflict["body"]["message"]


def test_collector_duplicate_click_and_concurrent_token(page: Page, servers) -> None:
    import json
    import urllib.request

    backend = servers["backend"]
    captured: list[dict] = []

    def handle_request(request) -> None:
        if request.url.endswith("/api/collector/3/actions") and request.method == "POST":
            captured.append(json.loads(request.post_data or "{}"))

    page.on("request", handle_request)
    page.goto(f"{servers['frontend']}/collector")
    row = _row_for(page, "COLL-0003")  # 运行中
    expect(row.locator("td").nth(-2)).to_have_text("运行中")

    # 在浏览器侧挂住真实 fetch：动作请求照常发出、响应先不 resolve，
    # 制造确定的「进行中」窗口来验证按钮禁用（不依赖 Playwright 路由的时序）。
    # 只挂住动作 POST，后续列表 GET 必须立即放行，否则刷新会被一起挂住。
    page.evaluate(
        """() => {
            let release;
            window.__hold = new Promise((resolve) => { release = resolve; });
            const originalFetch = window.fetch.bind(window);
            window.fetch = (...args) => {
                const response = originalFetch(...args);
                if (String(args[0]).includes('/api/collector/3/actions')) {
                    return response.then((res) => window.__hold.then(() => res));
                }
                return response;
            };
            window.__releaseHold = () => release();
            window.__restoreFetch = () => { window.fetch = originalFetch; };
        }"""
    )

    # 暂停采集是该行第 2 个动作按钮（提交启动=0、暂停采集=1、恢复采集=2、归档任务=3），
    # 用固定索引定位，避免按钮在进行中改文案为「执行中…」后按名称找不到。
    button = row.locator("button").nth(1)
    button.click()
    # 响应被挂起期间按钮必须禁用，避免重复提交。
    expect(button).to_be_disabled()
    expect(button).to_have_text("执行中…")
    # 挂起期间只发出了一个动作请求。
    assert len(captured) == 1
    assert captured[0]["action"] == "暂停采集" and captured[0]["token"]

    # 放行挂起的响应，真实后端结果回到页面并触发列表刷新（GET 不再被挂）。
    page.evaluate("() => { window.__releaseHold(); }")
    expect(row.locator("td").nth(-2)).to_have_text("已停用")
    expect(page.locator(".success-text")).to_have_text(
        "采集任务已暂停采集：运行中 → 已停用"
    )
    expect(button).to_be_enabled()
    expect(button).to_have_text("暂停采集")
    page.evaluate("() => window.__restoreFetch()")

    # 接口复现：同令牌并发 8 次，后端只执行一次（经页面同源代理发请求）。
    concurrent = page.evaluate(
        """async (token) => {
            const calls = Array.from({ length: 8 }, () =>
                fetch('/api/collector/3/actions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: '恢复采集', token }),
                }).then((res) => res.json())
            )
            return Promise.all(calls)
        }""",
        "e2e-parallel-collector",
    )
    executed = [item for item in concurrent if item["duplicate"] is False]
    duplicates = [item for item in concurrent if item["duplicate"] is True]
    assert len(executed) == 1 and len(duplicates) == 7
    assert all(item["ok"] is True for item in concurrent)

    # 重复响应可确认最终结果：同令牌再请求一次，回显已缓存的最终状态，不再执行。
    repeat = urllib.request.Request(
        f"{backend}/api/collector/3/actions",
        data=json.dumps({"action": "恢复采集", "token": "e2e-parallel-collector"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(repeat, timeout=5) as response:
        body = json.loads(response.read())
    assert body["duplicate"] is True and body["entry"]["status"] == "运行中"


# ----------------------------- 定时调度 -----------------------------


def test_scheduler_draft_skip_level_rejected_then_full_flow(page: Page, servers) -> None:
    page.goto(f"{servers['frontend']}/scheduler")
    expect(page.get_by_role("heading", name="定时调度管理")).to_be_visible()

    row = _row_for(page, "SCHE-0001")  # 草稿
    assert _status_of(row) == "草稿"

    # 草稿直接启用 = 跳级，必须展示后端原因且状态不变。
    _click_action(row, "启用计划")
    expect(page.locator(".error-text")).to_contain_text("禁止跳过校验")
    expect(row.locator("td").nth(-2)).to_have_text("草稿")

    # 正确顺序：提交校验 -> 启用 -> 停用 -> 再启用。
    _click_action(row, "提交校验")
    expect(row.locator("td").nth(-2)).to_have_text("待校验")
    _click_action(row, "启用计划")
    expect(row.locator("td").nth(-2)).to_have_text("已启用")
    _click_action(row, "停用计划")
    expect(row.locator("td").nth(-2)).to_have_text("已停用")
    _click_action(row, "启用计划")
    expect(row.locator("td").nth(-2)).to_have_text("已启用")


def test_scheduler_illegal_action_and_conflict(page: Page, servers) -> None:
    import json
    import urllib.request

    backend = servers["backend"]

    def post(body: dict) -> dict:
        req = urllib.request.Request(
            f"{backend}/api/scheduler/1/actions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read())

    # 接口复现冲突请求。
    conflict = post(
        {"action": "启用计划", "values": {"action": "停用计划"}, "token": "e2e-s-conflict"}
    )
    assert conflict["ok"] is False and "动作冲突" in conflict["message"]

    # 旧协议可用。
    legacy = post({"values": {"action": "提交校验"}, "token": "e2e-s-legacy"})
    assert legacy["ok"] is True and legacy["entry"]["status"] == "待校验"

    # 页面真实点击非法转移：待校验状态不能停用。
    page.goto(f"{servers['frontend']}/scheduler")
    row = _row_for(page, "SCHE-0001")
    expect(row.locator("td").nth(-2)).to_have_text("待校验")
    _click_action(row, "停用计划")
    expect(page.locator(".error-text")).to_contain_text("不允许「停用计划」")
    expect(row.locator("td").nth(-2)).to_have_text("待校验")


def test_scheduler_duplicate_token_executes_once(page: Page, servers) -> None:
    # 先进入应用页面，让相对地址的 fetch 经 vite 代理转发到后端。
    page.goto(f"{servers['frontend']}/scheduler")
    concurrent = page.evaluate(
        """async (token) => {
            const calls = Array.from({ length: 8 }, () =>
                fetch('/api/scheduler/3/actions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: '停用计划', token }),
                }).then((res) => res.json())
            )
            return Promise.all(calls)
        }""",
        "e2e-s-parallel",
    )
    assert len([item for item in concurrent if item["duplicate"] is False]) == 1
    assert all(item["entry"]["status"] == "已停用" for item in concurrent)

    # 页面最终展示与服务端一致（不靠前端改数据）。
    page.goto(f"{servers['frontend']}/scheduler")
    row = _row_for(page, "SCHE-0003")
    expect(row.locator("td").nth(-2)).to_have_text("已停用")
