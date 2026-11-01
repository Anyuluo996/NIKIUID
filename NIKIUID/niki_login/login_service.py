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
from ..utils.database import NikiUser, NikiCredential
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
    """发起登录:有保存的凭证先自动登录,失败再发网页链接。"""
    cred = await NikiCredential.get_latest_credential(
        user_id=ev.user_id, bot_id=ev.bot_id
    )
    if cred is not None:
        mask = cred.account_mask or "已保存账号"
        await bot.send(
            f"[无限暖暖] 检测到已保存的账号({mask}), 正在自动登录...",
            at_sender=bool(ev.group_id),
        )
        ok, text = await auto_login_with_credential(ev, cred)
        if ok:
            await send_niki_notify(bot, ev, text)
            await bot.send(
                "如需更换账号, 请先发送「退出登录」(会同时清除保存的账号密码)",
                at_sender=bool(ev.group_id),
            )
            return
        # 自动登录失败(密码改了/服务不可用等):告知原因后回退网页链接
        await send_niki_notify(
            bot, ev, f"自动登录失败: {text}\n已为你生成网页登录链接"
        )

    await _issue_login_link(bot, ev)


async def auto_login_with_credential(ev: Event, cred: NikiCredential) -> tuple[bool, str]:
    """用保存的凭证走账号密码登录 + 刷新,返回 (是否成功, 结果文本)。"""
    try:
        account, password = cred.reveal()
    except Exception:
        # 密文/盐损坏(如程序佐料变更后残留旧行):解密会抛错,走回退而不是崩命令
        logger.warning(f"[niki登录] 凭证解密失败 user_id={ev.user_id}, 忽略并回退链接")
        return False, "保存的凭证已损坏, 请重新登录"
    if not account or not password:
        return False, "保存的凭证已损坏, 请重新登录"
    return await _password_login_flow(
        user_id=ev.user_id, bot_id=ev.bot_id, account=account, password=password
    )


async def _issue_login_link(bot: Bot, ev: Event) -> None:
    """原有网页登录流程:发链接 → 后台等终态 → 通知结果。"""
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
    """轮询 LOGIN_CACHE 等终态。

    终态不从缓存移除:完成页 /niki/done 会继续轮询 /niki/status/{auth}
    展示真实结果,条目由 TTL 自然过期;终态条目不会被 _auth_token 复用。
    """
    waited = 0.0
    wait_s = await _login_ttl_s()
    while waited < wait_s:
        state: LoginState | None = LOGIN_CACHE.get(auth_token)
        if not state:
            return None
        if state.status in {"success", "failed"}:
            return state
        await asyncio.sleep(LOGIN_POLL_INTERVAL)
        waited += LOGIN_POLL_INTERVAL
    # 超时:仅回收未进入刷新阶段的会话。refreshing 的留给后台任务写终态,
    # 完成页仍能轮询到真实结果(凭证已保存,只是 bot 侧等超时了)
    state = LOGIN_CACHE.get(auth_token)
    if state and state.status != "refreshing":
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

    # 会话已过期被 TTL 回收:不再回写,避免留下无人消费的幽灵条目
    # (终态条目不会被 _auth_token 复用,但登录页 /niki/i/{auth} 会 404)
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
    # 幂等守卫:refreshing(刷新已在后台进行)与 success(终态已落,旧标签页
    # 仍停留在登录表单)都不再重走 sms_login —— 验证码已被消费必然失败,
    # 会把 refreshing/success 改写成 failed,污染完成页轮询到的真实结果。
    # failed 会话允许重试:验证码错了换个新验证码再提交是正常路径
    if state.status == "refreshing" or state.ok:
        return LoginResult.success(msg=state.msg or LoginMsg.SMS_VERIFIED)

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


async def perform_login_password(
    auth_token: str, account: str, password: str, remember: bool
) -> LoginResult:
    """网页侧:账号密码登录(可选记住凭证)。

    与 perform_login 相同的后台刷新模式:本接口只验证并立刻返回,
    前端跳转完成页,bot 侧结果由 _wait 轮询后通知。
    """
    state: LoginState | None = LOGIN_CACHE.get(auth_token)
    if not state:
        return LoginResult.fail(LoginMsg.session_expired())
    # 幂等守卫:同 perform_login
    if state.status == "refreshing" or state.ok:
        return LoginResult.success(msg=state.msg or LoginMsg.SMS_VERIFIED)

    login_result = await passport_login(account, password)
    if not login_result:
        state.status = "failed"
        state.ok = False
        state.msg = "账号密码登录失败,请检查账号密码是否正确"
        LOGIN_CACHE.set(auth_token, state)
        return LoginResult.fail(state.msg)

    # 记住账号密码:入库(AES-GCM 强加密);失败不影响登录本身
    if remember:
        try:
            await NikiCredential.save_credential(
                user_id=state.user_id,
                bot_id=state.bot_id,
                account=account,
                password=password,
            )
            logger.info(
                f"[niki登录] 网页侧保存凭证 user_id={state.user_id} "
                f"account={account[:3]}****"
            )
        except Exception as e:
            logger.warning(f"[niki登录] 保存凭证失败: {e!r}")

    state.status = "refreshing"
    LOGIN_CACHE.set(auth_token, state)

    token_info = {
        **login_result,
        "platform_user_id": state.user_id,
        "device_id": state.device_id,
    }

    task = asyncio.create_task(_refresh_login_state(auth_token, state, token_info))
    _BACKGROUND_REFRESH_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_REFRESH_TASKS.discard)

    return LoginResult.success(msg="登录成功, 请回到对话查看结果")


async def _password_login_flow(
    *,
    user_id: str,
    bot_id: str,
    account: str,
    password: str,
) -> tuple[bool, str]:
    """账号密码登录 + 数据刷新的共用流程(bot 直登与自动登录共用)。

    返回 (是否成功, 展示文本)。
    """
    login_result = await passport_login(account, password)
    if not login_result:
        return False, "账号密码登录失败,请检查账号密码是否正确"

    token_info = {
        **login_result,
        "platform_user_id": user_id,
        "device_id": "",
    }

    auto_refresh = bool(NikiConfig.get_config("NikiLoginAutoRefresh").data)

    try:
        refresh_result = await refresh_user_data(
            user_id=user_id,
            bot_id=bot_id,
            token_info=token_info,
            auto_refresh=auto_refresh,
        )
    except Exception as e:
        logger.exception(f"[niki登录] 账号密码登录后刷新异常: {e}")
        refresh_result = None

    if refresh_result and refresh_result.get("success"):
        nickname = refresh_result.get("nickname") or "搭配师"
        level = refresh_result.get("level") or 0
        return True, f"{LoginMsg.SUCCESS}\n搭配师: {nickname}\n等级: {level}"

    fail_msg = (refresh_result or {}).get(
        "refresh_status", "登录凭证已保存,但数据刷新失败"
    )
    # 刷新失败但凭证本身有效:视为登录成功(与网页侧口径一致)
    return True, fail_msg


async def logout(bot: Bot, ev: Event) -> None:
    """退出登录:删除当前账号,并清除保存的自动登录凭证。"""
    # 先清凭证:即使账号行已不存在,也不能留下会被自动登录的密码
    await NikiCredential.delete_credentials(user_id=ev.user_id, bot_id=ev.bot_id)

    user = await NikiUser.get_active(ev.user_id, ev.bot_id)
    if user is None:
        accounts = await NikiUser.list_accounts(ev.user_id, ev.bot_id)
        if not accounts:
            return await send_niki_notify(bot, ev, LoginMsg.NOT_LOGGED_IN)
        user = accounts[0]

    deleted = await NikiUser.delete_account(ev.user_id, ev.bot_id, user.openid)
    if not deleted:
        return await send_niki_notify(bot, ev, LoginMsg.NOT_LOGGED_IN)
    await send_niki_notify(
        bot, ev, f"{LoginMsg.LOGOUT_DONE}\n保存的账号密码已一并清除"
    )


async def logout_all(bot: Bot, ev: Event) -> None:
    """全部登出(同时清除保存的凭证)。"""
    await NikiCredential.delete_credentials(user_id=ev.user_id, bot_id=ev.bot_id)
    count = await NikiUser.delete_all(ev.user_id, ev.bot_id)
    if count == 0:
        return await send_niki_notify(bot, ev, LoginMsg.NOT_LOGGED_IN)
    await send_niki_notify(
        bot, ev, f"{LoginMsg.LOGOUT_ALL_DONE}\n保存的账号密码已一并清除"
    )


async def login_by_password(bot: Bot, ev: Event, account: str, password: str) -> None:
    """账号密码直登(无需网页)。

    流程:passport_login 拿 token → 保存凭证(强加密, 供自动登录)
    → refresh_user_data 刷新数据 → 通知结果。
    """
    await bot.send("[无限暖暖] 正在登录...", at_sender=bool(ev.group_id))

    ok, text = await _password_login_flow(
        user_id=ev.user_id, bot_id=ev.bot_id, account=account, password=password
    )
    if not ok:
        return await send_niki_notify(bot, ev, text)

    # 登录有效:保存凭证供 nk登录 自动登录(失败不阻断登录结果)
    saved_note = ""
    try:
        await NikiCredential.save_credential(
            user_id=ev.user_id, bot_id=ev.bot_id, account=account, password=password
        )
        saved_note = "\n已加密保存账号密码, 下次发送「登录」将自动登录"
        logger.info(f"[niki登录] 保存凭证 user_id={ev.user_id} account={account[:3]}****")
    except Exception as e:
        logger.warning(f"[niki登录] 保存凭证失败: {e!r}")

    await send_niki_notify(bot, ev, f"{text}{saved_note}")
