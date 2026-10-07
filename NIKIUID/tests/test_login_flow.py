"""登录后台刷新流程测试。

覆盖审查修复的关键行为:
- perform_login 短信验证通过即返回,数据刷新在后台任务完成
- refreshing 状态下重复提交(响应丢失后重试)不污染会话状态
- _wait 轮询到后台推入的终态
- 终态会话不复用(_auth_token)、被回收的会话不回写(_refresh_login_state)
"""

from __future__ import annotations

import asyncio

import pytest

from gsuid_core.plugins.NIKIUID.NIKIUID.niki_login import login_service
from gsuid_core.plugins.NIKIUID.NIKIUID.niki_login.login_service import (
    LOGIN_CACHE,
    LoginState,
    LoginResult,
    _wait,
    _auth_token,
    perform_login,
    _refresh_login_state,
)


class _FakeConfig:
    def __init__(self, data) -> None:
        self.data = data


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch):
    """清空缓存 + stub 配置,隔离模块级状态。"""
    LOGIN_CACHE.clear()
    monkeypatch.setattr(
        login_service.NikiConfig, "get_config", lambda _k: _FakeConfig(True)
    )
    yield
    LOGIN_CACHE.clear()
    for task in list(login_service._BACKGROUND_REFRESH_TASKS):
        task.cancel()


def _make_state(token: str, user_id: str = "user1") -> LoginState:
    state = LoginState(user_id=user_id, bot_id="test", group_id=None)
    LOGIN_CACHE.set(token, state)
    return state


@pytest.mark.asyncio
async def test_perform_login_returns_before_refresh_finishes(monkeypatch):
    """刷新被阻塞时 perform_login 也应立即返回 success。"""
    gate = asyncio.Event()

    async def fake_refresh(**_kwargs):
        await gate.wait()
        return {"success": True, "nickname": "小暖", "level": 60}

    async def fake_sms(_mobile, _code, device_id=""):
        return {"token": "t", "openid": "o", "client_id": 1106, "area_id": 1}

    monkeypatch.setattr(login_service, "refresh_user_data", fake_refresh)
    monkeypatch.setattr(login_service, "sms_login", fake_sms)

    token = "tok-gate"
    _make_state(token)

    result = await perform_login(token, "13800000000", "1234")
    assert isinstance(result, LoginResult)
    assert result.ok is True

    # 返回后、放行前:会话处于 refreshing,后台任务尚未完成
    assert LOGIN_CACHE.get(token).status == "refreshing"

    gate.set()
    await asyncio.gather(*login_service._BACKGROUND_REFRESH_TASKS)
    assert LOGIN_CACHE.get(token).status == "success"
    assert LOGIN_CACHE.get(token).result.get("nickname") == "小暖"


@pytest.mark.asyncio
async def test_perform_login_idempotent_while_refreshing(monkeypatch):
    """refreshing 状态下重复提交(响应丢失后重试)不改写状态、不再走 sms_login。"""

    async def fake_refresh(**_kwargs):
        await asyncio.sleep(0.05)
        return {"success": True, "nickname": "小暖", "level": 60}

    async def ok_sms(_mobile, _code, device_id=""):
        return {"token": "t", "openid": "o", "client_id": 1106, "area_id": 1}

    sms_calls: list[int] = []
    monkeypatch.setattr(login_service, "refresh_user_data", fake_refresh)

    def counting_sms(fn):
        async def wrapper(*args, **kwargs):
            sms_calls.append(1)
            return await fn(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(
        login_service, "sms_login", counting_sms(ok_sms)
    )

    token = "tok-retry"
    _make_state(token)
    first = await perform_login(token, "13800000000", "1234")
    assert first.ok is True
    assert len(sms_calls) == 1

    # 模拟用户拿同一链接重试:即使验证码已被消费,也不应再次走 sms_login
    retry = await perform_login(token, "13800000000", "1234")
    assert retry.ok is True
    assert len(sms_calls) == 1

    await asyncio.gather(*login_service._BACKGROUND_REFRESH_TASKS)
    assert LOGIN_CACHE.get(token).status == "success"


@pytest.mark.asyncio
async def test_wait_polls_background_terminal_state(monkeypatch):
    """_wait 能轮询到后台任务推入的终态。"""

    async def fake_refresh(**_kwargs):
        await asyncio.sleep(0.05)
        return {"success": True, "nickname": "小暖", "level": 60}

    async def fake_sms(_mobile, _code, device_id=""):
        return {"token": "t", "openid": "o", "client_id": 1106, "area_id": 1}

    monkeypatch.setattr(login_service, "refresh_user_data", fake_refresh)
    monkeypatch.setattr(login_service, "sms_login", fake_sms)
    monkeypatch.setattr(login_service, "LOGIN_POLL_INTERVAL", 0.01)

    token = "tok-wait"
    _make_state(token)
    await perform_login(token, "13800000000", "1234")

    result = await _wait(token)
    assert result is not None
    assert result.status == "success"
    # 终态被消费后移除
    assert LOGIN_CACHE.get(token) is None


@pytest.mark.asyncio
async def test_auth_token_skips_terminal_sessions(monkeypatch):
    """已有终态会话的用户再发起登录,生成新 token 而不是复用死会话。"""
    dead = _make_state("tok-dead")
    dead.status = "success"
    dead.ok = True

    token = _auth_token("user1")
    assert token != "tok-dead"


@pytest.mark.asyncio
async def test_refresh_task_does_not_resurrect_collected_session(monkeypatch):
    """会话已被回收(TTL 到期等)时,后台刷新完成不再回写缓存。"""

    async def fake_refresh(**_kwargs):
        return {"success": True, "nickname": "小暖", "level": 60}

    monkeypatch.setattr(login_service, "refresh_user_data", fake_refresh)

    token = "tok-collected"
    state = _make_state(token)
    state.status = "refreshing"

    # 模拟 _wait 在刷新完成前把会话回收
    LOGIN_CACHE.pop(token)

    await _refresh_login_state(token, state, {"token": "t", "openid": "o"})
    assert LOGIN_CACHE.get(token) is None
