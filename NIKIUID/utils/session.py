"""统一鉴权会话抽象。

参考 NTEUID/utils/session.py,把「取活跃账号 + 未登录提示」收敛到一处。
各命令复用 require_user(),避免重复 get_active → list_accounts → not_logged_in 样板。
"""

from __future__ import annotations

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event

from .msgs import CommonMsg, send_niki_notify
from .database import NikiUser


async def require_user(bot: Bot, ev: Event) -> NikiUser | None:
    """取当前聊天用户的活跃账号。

    未登录时自动发送提示消息并返回 None,调用方应直接 return:
        user = await require_user(bot, ev)
        if user is None:
            return

    token 失效(status="expired")的账号会被 get_active 过滤掉。
    """
    user = await NikiUser.get_active(ev.user_id, ev.bot_id)
    if user is None:
        accounts = await NikiUser.list_accounts(ev.user_id, ev.bot_id)
        has_expired = bool(accounts)  # 有账号但没活跃的 = 可能 token 过期
        await send_niki_notify(bot, ev, CommonMsg.not_logged_in(has_expired))
        if has_expired:
            logger.info(
                f"[niki] user_id={ev.user_id} 有 {len(accounts)} 个账号但无活跃,可能 token 过期"
            )
    return user
