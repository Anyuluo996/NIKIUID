"""登录会话管理。

流程(参考 NTEUID login_service.py):
1. 用户发「niki登录」→ request_login 生成 auth token,写入 LOGIN_CACHE,
   发登录链接给用户,然后后台 _wait 轮询 cache 等终态
2. 用户在网页填手机号 → POST /niki/sendSmsCode → send_login_sms 调 passport
3. 用户填验证码 → POST /niki/login → perform_login 调 passport.sms_login,
   成功后写 LOGIN_CACHE,触发后台落库 + 刷新数据
4. 后台 _wait 收到终态 → login_done 通知用户结果
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any
from dataclasses import field, dataclass

from gsuid_core.bot import Bot
from gsuid_core.config import core_config
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment

from ..utils.msgs import LoginMsg, send_niki_notify
from ..utils.cache import TimedCache
from ..utils.utils import get_public_ip
from ..utils.database import NikiUser
from ..utils.auth.crypto import generate_device_id
from ..utils.auth.passport import sms_login, send_sms_code, passport_login
from ..niki_config.niki_config import NikiConfig
from ..utils.services.refresh_service import refresh_user_data

# cache 容量上限;实际等待时长由 NikiLoginTTL 决定
_MAX_LOGIN_TTL_S = 3600
LOGIN_CACHE: TimedCache = TimedCache(timeout=_MAX_LOGIN_TTL_S, maxsize=256)
LOGIN_POLL_INTERVAL = 2.0

# 后台刷新任务强引用集,防止 task 被 GC
_BACKGROUND_REFRESH_TASKS: set[asyncio.Task] = set()


@dataclass
class LoginState:
    """单次登录会话的状态。"""

    user_id: str
    bot_id: str
    group_id: str | None
    device_id: str = field(default_factory=generate_device_id)
    status: str = "pending"  # pending | refreshing | success | failed
    ok: bool = False
    msg: str = ""
    result: dict[str, Any] | None = None  # 刷新结果(success 时)


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    msg: str = ""

    @classmethod
    def fail(cls, msg: str) -> "LoginResult":
        return cls(ok=False, msg=msg)

    @classmethod
    def success(cls, msg: str = "") -> "LoginResult":
        return cls(ok=True, msg=msg)


def _auth_token(user_id: str) -> str:
    """生成高熵随机 auth token,避免 user_id 可推导导致的会话劫持。

    用 user_id 作为 key 在 LOGIN_CACHE 里查是否已有进行中的会话(复用链接体验),
    但链接本身携带的是不可预测的随机 token,攻击者无法从公开的 user_id 推出。
    """
    # 先查该用户是否已有活跃 token,有就复用(同一用户不重复开 wait),
    # 终态(success/failed)会话不算活跃:复用会让登录页直接 303 到完成页,
    # 用户拿到打不开的链接且 bot 永远不会通知
    for tok, state in LOGIN_CACHE.items():
        if (
            state
            and getattr(state, "user_id", None) == user_id
            and getattr(state, "status", None) not in {"success", "failed"}
        ):
            return tok
    return secrets.token_urlsafe(16)


async def _login_ttl_s() -> int:
    return int(NikiConfig.get_config("NikiLoginTTL").data)


async def _login_page_url() -> str:
    """推算对外可访问的登录页 URL。

    优先用配置 NikiLoginUrl;留空则用 Core 的 HOST/PORT,localhost 自动探测公网 IP。
    """
    url = NikiConfig.get_config("NikiLoginUrl").data.strip()
    if url:
        return url if url.startswith("http") else f"https://{url}"

    host = core_config.get_config("HOST")
    port = core_config.get_config("PORT")
    if host in {"localhost", "127.0.0.1"}:
        host = "localhost"
    else:
        host = await get_public_ip(host)
    return f"http://{host}:{port}"


async def _send_login_link(bot: Bot, ev: Event, url: str) -> None:
    """发送登录链接给用户。支持合并转发(避免风控)。"""
    forward = bool(NikiConfig.get_config("NikiLoginForward").data)
    lines = [
        f"[无限暖暖] 您的id为【{ev.user_id}】",
        LoginMsg.LINK_COPY,
        f" {url}",
        LoginMsg.link_ttl(),
    ]
    if forward:
        await bot.send(MessageSegment.node(lines))
    else:
        await bot.send("\n".join(lines), at_sender=bool(ev.group_id))


async def request_login(bot: Bot, ev: Event) -> None:
    """发起一次网页登录会话。"""
    auth_token = _auth_token(ev.user_id)
    login_url = f"{await _login_page_url()}/niki/i/{auth_token}"
    await _send_login_link(bot, ev, login_url)

    # 已有进行中的登录:复用同一个链接,不另开 wait 循环
    if LOGIN_CACHE.get(auth_token):
        return

    LOGIN_CACHE.set(
        auth_token,
        LoginState(
            user_id=ev.user_id,
            bot_id=ev.bot_id,
            group_id=ev.group_id,
        ),
    )

    result = await _wait(auth_token)
    if result is None:
        return await send_niki_notify(bot, ev, LoginMsg.timeout())
    if not result.ok:
        return await send_niki_notify(bot, ev, result.msg)

    # 刷新结果里带 nickname/level,直接展示;nickname 为空说明刷新失败,
    # 把失败原因(result.message)带给用户
    nickname = (result.result or {}).get("nickname") or "搭配师"
    level = (result.result or {}).get("level") or 0
    extra = (result.result or {}).get("message") or ""
    text = f"{LoginMsg.SUCCESS}\n搭配师: {nickname}\n等级: {level}"
    if extra:
        text += f"\n{extra}"
    await send_niki_notify(bot, ev, text)


async def _wait(auth_token: str) -> LoginState | None:
    """轮询 LOGIN_CACHE 等终态。"""
    waited = 0.0
    wait_s = await _login_ttl_s()
    while waited < wait_s:
        state: LoginState | None = LOGIN_CACHE.get(auth_token)
        if not state:
            return None
        if state.status in {"success", "failed"}:
            LOGIN_CACHE.pop(auth_token)
            return state
        await asyncio.sleep(LOGIN_POLL_INTERVAL)
        waited += LOGIN_POLL_INTERVAL
    LOGIN_CACHE.pop(auth_token)
    return None


async def send_login_sms(auth_token: str, mobile: str) -> LoginResult:
    """网页侧:发送短信验证码。"""
    state: LoginState | None = LOGIN_CACHE.get(auth_token)
    if not state:
        return LoginResult.fail(LoginMsg.session_expired())

    result = await send_sms_code(mobile, device_id=state.device_id)
    if result.get("success"):
        # passport 可能回传新的 device_id,更新到 state
        new_device = result.get("device_id")
        if new_device:
            state.device_id = new_device
        return LoginResult.success(msg=LoginMsg.SMS_SENT)
    return LoginResult.fail(result.get("message", LoginMsg.SMS_SEND_FAILED))


async def _refresh_login_state(
    auth_token: str, state: LoginState, token_info: dict[str, Any]
) -> None:
    """后台执行登录后的数据刷新,把 LOGIN_CACHE 推到终态。

    独立于 HTTP 请求运行:_wait 轮询到终态后给 bot 用户发通知。
    刷新失败但凭证已保存时仍置 success(与原同步逻辑一致),
    失败文案通过 state.result 带回。
    """
    try:
        auto_refresh = bool(NikiConfig.get_config("NikiLoginAutoRefresh").data)
        refresh_result = await refresh_user_data(
            user_id=state.user_id,
            bot_id=state.bot_id,
            token_info=token_info,
            auto_refresh=auto_refresh,
        )
    except Exception as e:
        logger.exception(f"[niki登录] 刷新数据异常 user_id={state.user_id}: {e}")
        refresh_result = None

    # 会话已被 _wait 回收(TTL 到期等):不再回写,避免留下无人消费的
    # 终态幽灵条目(会被 _auth_token 复用,导致用户拿到打不开的旧链接)
    if not LOGIN_CACHE.get(auth_token):
        return

    if refresh_result and refresh_result.get("success"):
        state.status = "success"
        state.ok = True
        state.msg = LoginMsg.SMS_VERIFIED
        state.result = refresh_result
    else:
        fail_msg = (refresh_result or {}).get(
            "refresh_status", "登录凭证已保存，但数据刷新失败"
        )
        state.status = "success"
        state.ok = True
        state.msg = LoginMsg.SMS_VERIFIED
        state.result = {"nickname": "", "level": 0, "message": fail_msg}
    LOGIN_CACHE.set(auth_token, state)


async def perform_login(auth_token: str, mobile: str, code: str) -> LoginResult:
    """网页侧:短信验证码登录。

    只做 passport 短信验证;数据刷新放到后台任务执行,本接口立即返回,
    前端马上跳转完成页(原实现在请求内同步刷新,套装图片下载动辄数十秒,
    超过网关/浏览器超时后 fetch 中断,页面卡在"验证中"不跳转)。
    bot 侧结果由 request_login 的 _wait 轮询 LOGIN_CACHE 终态后通知。
    """
    state: LoginState | None = LOGIN_CACHE.get(auth_token)
    if not state:
        return LoginResult.fail(LoginMsg.session_expired())
    # 幂等:刷新已在后台进行(首次请求可能因网络中断未到达浏览器),
    # 同一会话重复提交不再走 sms_login,避免把 refreshing 改写成 failed
    if state.status == "refreshing":
        return LoginResult.success(msg=LoginMsg.SMS_VERIFIED)

    login_result = await sms_login(mobile, code, device_id=state.device_id)
    if not login_result:
        state.status = "failed"
        state.ok = False
        state.msg = LoginMsg.SMS_LOGIN_FAILED
        LOGIN_CACHE.set(auth_token, state)
        return LoginResult.fail(LoginMsg.SMS_LOGIN_FAILED)

    # 短信验证通过:进入刷新阶段(后台),立即返回成功让前端跳转
    state.status = "refreshing"
    LOGIN_CACHE.set(auth_token, state)

    # 把 platform_user_id 带进去,refresh_service 会用它做存储 key
    token_info = {
        **login_result,
        "platform_user_id": state.user_id,
        "device_id": state.device_id,
    }

    task = asyncio.create_task(_refresh_login_state(auth_token, state, token_info))
    _BACKGROUND_REFRESH_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_REFRESH_TASKS.discard)

    return LoginResult.success(msg=LoginMsg.SMS_VERIFIED)


async def logout(bot: Bot, ev: Event) -> None:
    """退出登录:删除当前账号。"""
    user = await NikiUser.get_active(ev.user_id, ev.bot_id)
    if user is None:
        accounts = await NikiUser.list_accounts(ev.user_id, ev.bot_id)
        if not accounts:
            return await send_niki_notify(bot, ev, LoginMsg.NOT_LOGGED_IN)
        user = accounts[0]

    deleted = await NikiUser.delete_account(ev.user_id, ev.bot_id, user.openid)
    if not deleted:
        return await send_niki_notify(bot, ev, LoginMsg.NOT_LOGGED_IN)
    await send_niki_notify(bot, ev, LoginMsg.LOGOUT_DONE)


async def logout_all(bot: Bot, ev: Event) -> None:
    """全部登出。"""
    count = await NikiUser.delete_all(ev.user_id, ev.bot_id)
    if count == 0:
        return await send_niki_notify(bot, ev, LoginMsg.NOT_LOGGED_IN)
    await send_niki_notify(bot, ev, LoginMsg.LOGOUT_ALL_DONE)


async def login_by_password(bot: Bot, ev: Event, account: str, password: str) -> None:
    """账号密码直登(无需网页)。

    流程:passport_login 拿 token → refresh_user_data 刷新数据 → 通知结果。
    """
    await bot.send("[无限暖暖] 正在登录...", at_sender=bool(ev.group_id))

    login_result = await passport_login(account, password)
    if not login_result:
        return await send_niki_notify(bot, ev, "账号密码登录失败,请检查账号密码是否正确")

    token_info = {
        **login_result,
        "platform_user_id": ev.user_id,
        "device_id": "",
    }

    auto_refresh = bool(NikiConfig.get_config("NikiLoginAutoRefresh").data)

    try:
        refresh_result = await refresh_user_data(
            user_id=ev.user_id,
            bot_id=ev.bot_id,
            token_info=token_info,
            auto_refresh=auto_refresh,
        )
    except Exception as e:
        logger.exception(f"[niki登录] 账号密码登录后刷新异常: {e}")
        refresh_result = None

    if refresh_result and refresh_result.get("success"):
        nickname = refresh_result.get("nickname") or "搭配师"
        level = refresh_result.get("level") or 0
        await send_niki_notify(
            bot, ev, f"{LoginMsg.SUCCESS}\n搭配师: {nickname}\n等级: {level}"
        )
    else:
        fail_msg = (refresh_result or {}).get(
            "refresh_status", "登录凭证已保存,但数据刷新失败"
        )
        await send_niki_notify(bot, ev, fail_msg)
