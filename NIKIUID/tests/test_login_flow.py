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
    _password_login_flow,
    _refresh_login_state,
    perform_login_password,
)


class _FakeConfig:
    def __init__(self, data) -> None:
        self.data = data


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch):
    """清空缓存 + stub 配置,隔离模块级状态。"""
    LOGIN_CACHE.clear()
    monkeypatch.setattr(login_service.NikiConfig, "get_config", lambda _k: _FakeConfig(True))
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

    monkeypatch.setattr(login_service, "sms_login", counting_sms(ok_sms))

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
    # 终态保留在缓存里:完成页 /niki/done 会轮询 /niki/status 读取真实结果,
    # 由 TTL 自然过期(_auth_token 不会复用终态会话)
    assert LOGIN_CACHE.get(token) is not None
    assert LOGIN_CACHE.get(token).status == "success"


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


@pytest.mark.asyncio
async def test_perform_login_does_not_rewrite_success_session(monkeypatch):
    """success 终态后旧表单重复提交:不重走 sms_login、不改写状态。

    终态不再被 _wait 消费移除后,旧标签页可能仍停留在登录表单;
    此时的重复提交若重走 sms_login,验证码已被消费必然失败,
    会把 success 改写成 failed,污染完成页轮询到的真实结果。
    """

    async def no_sms(_mobile, _code, device_id=""):
        raise AssertionError("success 会话不应再走 sms_login")

    monkeypatch.setattr(login_service, "sms_login", no_sms)

    token = "tok-success-retry"
    state = _make_state(token)
    state.status = "success"
    state.ok = True
    state.msg = login_service.LoginMsg.SMS_VERIFIED

    result = await perform_login(token, "13800000000", "1234")
    assert result.ok is True
    remaining = LOGIN_CACHE.get(token)
    assert remaining.status == "success"
    assert remaining.ok is True


@pytest.mark.asyncio
async def test_wait_timeout_keeps_refreshing_drops_pending(monkeypatch):
    """_wait 超时:refreshing 会话保留(后台任务还要写终态),pending 回收。"""

    async def fake_ttl():
        return 0.03

    monkeypatch.setattr(login_service, "_login_ttl_s", fake_ttl)
    monkeypatch.setattr(login_service, "LOGIN_POLL_INTERVAL", 0.01)

    refreshing_token = "tok-timeout-refreshing"
    state = _make_state(refreshing_token)
    state.status = "refreshing"

    pending_token = "tok-timeout-pending"
    _make_state(pending_token)

    assert await _wait(refreshing_token) is None
    kept = LOGIN_CACHE.get(refreshing_token)
    assert kept is not None
    assert kept.status == "refreshing"

    assert await _wait(pending_token) is None
    assert LOGIN_CACHE.get(pending_token) is None


@pytest.mark.asyncio
async def test_perform_login_password_saves_when_remember(monkeypatch):
    """网页密码登录 + remember=true:立即返回成功,凭证入库,刷新后台完成。"""

    async def fake_refresh(**_kwargs):
        await asyncio.sleep(0.02)
        return {"success": True, "nickname": "小暖", "level": 60}

    async def fake_passport(_account, _password):
        return {"token": "t", "openid": "o", "client_id": 1106, "area_id": 1}

    saved: dict = {}

    async def fake_save(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(login_service, "refresh_user_data", fake_refresh)
    monkeypatch.setattr(login_service, "passport_login", fake_passport)
    monkeypatch.setattr(login_service.NikiCredential, "save_credential", fake_save)

    token = "tok-pwd-remember"
    _make_state(token)

    result = await perform_login_password(token, "13800000000", "pw123", True)
    assert result.ok is True
    assert saved.get("account") == "13800000000"
    assert saved.get("password") == "pw123"
    assert LOGIN_CACHE.get(token).status == "refreshing"

    await asyncio.gather(*login_service._BACKGROUND_REFRESH_TASKS)
    assert LOGIN_CACHE.get(token).status == "success"


@pytest.mark.asyncio
async def test_perform_login_password_without_remember_skips_save(monkeypatch):
    """remember=false:不写凭证表。"""

    async def fake_refresh(**_kwargs):
        return {"success": True, "nickname": "小暖", "level": 60}

    async def fake_passport(_account, _password):
        return {"token": "t", "openid": "o", "client_id": 1106, "area_id": 1}

    calls: list[dict] = []

    async def fake_save(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(login_service, "refresh_user_data", fake_refresh)
    monkeypatch.setattr(login_service, "passport_login", fake_passport)
    monkeypatch.setattr(login_service.NikiCredential, "save_credential", fake_save)

    token = "tok-pwd-noremember"
    _make_state(token)

    result = await perform_login_password(token, "13800000000", "pw123", False)
    assert result.ok is True
    assert calls == []
    await asyncio.gather(*login_service._BACKGROUND_REFRESH_TASKS)


@pytest.mark.asyncio
async def test_perform_login_password_fail_marks_failed(monkeypatch):
    """密码错误:返回 fail,会话置 failed;failed 允许重试。"""

    async def bad_passport(_account, _password):
        return None

    monkeypatch.setattr(login_service, "passport_login", bad_passport)

    token = "tok-pwd-fail"
    _make_state(token)

    result = await perform_login_password(token, "13800000000", "wrong", True)
    assert result.ok is False
    assert LOGIN_CACHE.get(token).status == "failed"


@pytest.mark.asyncio
async def test_perform_login_password_idempotent_while_refreshing(monkeypatch):
    """refreshing 状态下重复提交不重走 passport_login。"""

    async def fake_refresh(**_kwargs):
        return {"success": True, "nickname": "小暖", "level": 60}

    async def fake_passport(_account, _password):
        return {"token": "t", "openid": "o", "client_id": 1106, "area_id": 1}

    calls: list[int] = []

    def counting(fn):
        async def wrapper(*args, **kwargs):
            calls.append(1)
            return await fn(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(login_service, "refresh_user_data", fake_refresh)
    monkeypatch.setattr(login_service, "passport_login", counting(fake_passport))

    token = "tok-pwd-retry"
    _make_state(token)

    first = await perform_login_password(token, "13800000000", "pw123", False)
    assert first.ok is True
    assert len(calls) == 1

    retry = await perform_login_password(token, "13800000000", "pw123", False)
    assert retry.ok is True
    assert len(calls) == 1
    await asyncio.gather(*login_service._BACKGROUND_REFRESH_TASKS)


@pytest.mark.asyncio
async def test_password_login_flow_results(monkeypatch):
    """bot 侧共用流程:成功带昵称文案,失败带错误文案。"""

    async def ok_passport(_account, _password):
        return {"token": "t", "openid": "o", "client_id": 1106, "area_id": 1}

    async def bad_passport(_account, _password):
        return None

    async def ok_refresh(**_kwargs):
        return {"success": True, "nickname": "安雨落", "level": 100}

    monkeypatch.setattr(login_service, "passport_login", ok_passport)
    monkeypatch.setattr(login_service, "refresh_user_data", ok_refresh)
    ok, text = await _password_login_flow(user_id="u1", bot_id="test", account="a", password="p")
    assert ok is True
    assert "安雨落" in text

    monkeypatch.setattr(login_service, "passport_login", bad_passport)
    fail, fail_text = await _password_login_flow(user_id="u1", bot_id="test", account="a", password="p")
    assert fail is False
    assert "失败" in fail_text
