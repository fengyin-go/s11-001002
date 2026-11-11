"""动作接口共享逻辑：双协议动作解析、冲突拒绝与操作令牌幂等。

历史问题：前端把动作放在请求体顶层 ``action``，而路由只从 ``values.action`` 取，
导致动作丢失、后端业务拒绝（HTTP 200、ok=false），前端却只按 HTTP 状态判断成功。

本模块统一收口两件事：
1. ``resolve_action``：同时识别顶层 ``action``（新协议）和 ``values.action``
   （旧协议）；两处都传且取值不一致时判定为冲突并拒绝，绝不擅自挑一个执行。
2. ``IdempotencyStore``：带操作令牌的请求按「模块 + 记录 + 令牌」缓存最终结果，
   同一令牌的重复或并发提交只执行一次，后续请求原样拿到同一份最终结果。
"""
from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from typing import Any

from app.schemas import EntryPayload

# 业务动作的执行结果：是否成功、记录快照（失败时为 None）、给用户看的原因。
ActionOutcome = tuple[bool, dict[str, Any] | None, str]


def resolve_action(payload: EntryPayload) -> tuple[str, str | None]:
    """从请求体解析动作，兼容旧协议并处理双输入冲突。

    返回 ``(动作, 错误说明)``：出错时动作为空字符串、错误说明不为空。
    """
    top_level = (payload.action or "").strip()
    nested = str(payload.values.get("action") or "").strip()
    if top_level and nested:
        if top_level != nested:
            return "", (
                "动作冲突：顶层 action=「{0}」与 values.action=「{1}」取值不一致，"
                "请求已拒绝，请只保留一处动作入参".format(top_level, nested)
            )
        # 两处一致视为同一动作，按新协议正常执行。
        return top_level, None
    action = top_level or nested
    if not action:
        return "", "缺少动作参数：请在顶层 action（或兼容旧协议的 values.action）中指定要执行的动作"
    return action, None


class IdempotencyStore:
    """按操作令牌缓存动作最终结果的内存幂等存储。"""

    def __init__(self) -> None:
        self._results: dict[tuple[str, int, str], dict[str, Any]] = {}
        self._locks: dict[tuple[str, int, str], threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock_for(self, key: tuple[str, int, str]) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def execute(
        self,
        *,
        module: str,
        entry_id: int,
        token: str,
        action: str,
        func: Callable[[], ActionOutcome],
    ) -> tuple[dict[str, Any], bool, bool]:
        """执行一次带令牌的动作。

        返回 ``(结果体, 是否重复命中, 是否令牌动作冲突)``：
        - 首次提交：执行 ``func`` 并缓存最终结果（含业务拒绝），duplicate=False；
        - 同令牌重复/并发提交：不再执行，直接返回缓存的最终结果，duplicate=True；
        - 同令牌却换了动作：拒绝复用，返回 conflict=True，由路由层报 409。
        """
        key = (module, entry_id, token)
        with self._lock_for(key):
            cached = self._results.get(key)
            if cached is not None:
                if cached["action"] != action:
                    return {}, False, True
                repeat = {k: v for k, v in cached.items() if k != "action"}
                repeat["duplicate"] = True
                return repeat, True, False

            ok, entry, message = func()
            record = {
                "ok": ok,
                "message": message,
                "entry": copy.deepcopy(entry),
                "token": token,
                "duplicate": False,
                "action": action,
            }
            self._results[key] = record
            return {k: v for k, v in record.items() if k != "action"}, False, False

    def reset(self) -> None:
        """清空幂等缓存（供测试重置环境）。"""
        with self._guard:
            self._results.clear()


idempotency = IdempotencyStore()
