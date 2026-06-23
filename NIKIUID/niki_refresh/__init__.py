"""NIKIUID 刷新命令。

重新拉取奇想手账数据并更新本地缓存。token 过期时会提示重新登录。
"""

from __future__ import annotations

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.sv import SV

from ..niki_config.niki_config import NikiConfig
from ..utils.database import NikiUser
from ..utils.msgs import CommonMsg, RefreshMsg, send_niki_notify
from ..utils.services.refresh_service import refresh_user_data

sv_niki_refresh = SV("niki刷新")


@sv_niki_refresh.on_command(("刷新", "sx", "sync"), block=True)
async def niki_refresh_cmd(bot: Bot, ev: Event):
    """niki刷新 / nk刷新 - 重新拉取奇想手账数据"""
    user = await NikiUser.get_active(ev.user_id, ev.bot_id)
    if user is None:
        accounts = await NikiUser.list_accounts(ev.user_id, ev.bot_id)
        await send_niki_notify(bot, ev, CommonMsg.not_logged_in(bool(accounts)))
        return

    await bot.send(f"[无限暖暖] {RefreshMsg.REFRESHING}", at_sender=bool(ev.group_id))

    token_info = {
        "token": user.token,
        "openid": user.openid,
        "client_id": user.client_id,
        "area_id": user.area_id,
        "device_id": user.device_id,
    }

    debug_log = bool(NikiConfig.get_config("NikiDebugLog").data)

    try:
        result = await refresh_user_data(
            user_id=ev.user_id,
            bot_id=ev.bot_id,
            token_info=token_info,
            auto_refresh=True,
            enable_debug_log=debug_log,
        )
    except Exception as e:
        logger.exception(f"[niki刷新] 刷新异常 user_id={ev.user_id}: {e}")
        await send_niki_notify(bot, ev, RefreshMsg.FAILED)
        return

    if result is None or not result.get("success"):
        await send_niki_notify(bot, ev, RefreshMsg.FAILED)
        return

    nickname = result.get("nickname") or "未知"
    level = result.get("level") or 0
    await send_niki_notify(bot, ev, RefreshMsg.success(nickname, level))
