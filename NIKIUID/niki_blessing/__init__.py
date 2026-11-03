"""NIKIUID 祝福闪光命令。

- niki祝福闪光 / nk祝福闪光 / nk闪光 - 查看我的祝福闪光收集进度(矩阵图)
- 支持页码参数: 祝福闪光2 / nk闪光3(33 套按星级分页, 每页 11 套)
"""

from __future__ import annotations

import re

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment

from ..utils.msgs import CardMsg, CommonMsg, send_niki_notify
from ..utils.session import require_user
from ..utils.render_image import render_html_to_image
from ..utils.storage_cache import load_cached_data
from ..niki_config.niki_config import NikiConfig
from ..utils.render_blessing_card import render_blessing_card
from ..utils.resource.RESOURCE_PATH import USER_DATA_PATH

sv_niki_blessing = SV("niki祝福闪光")

# 「祝福闪光 / 闪光 / zhsg」后可跟页码, 空格可有可无
# on_regex 传原始 pattern 字符串(部分 core 版本不接受编译后的 re.Pattern)
_BLESSING_PATTERN = r"^(?:祝福闪光|闪光|zhsg)\s*(\d*)$"
_BLESSING_RE = re.compile(_BLESSING_PATTERN)


@sv_niki_blessing.on_regex(
    _BLESSING_PATTERN,
    block=True,
    to_ai="""查看无限暖暖祝福闪光收集矩阵

    当用户问祝福闪光、闪光收集进度、闪光配色收集时调用。

    Args:
        text: 消息格式为 "祝福闪光"、"闪光" 或 "zhsg",可带页码如 "闪光2"。
              不带页码默认第 1 页(33 套按星级分页,每页 11 套)
    """,
)
async def niki_blessing_cmd(bot: Bot, ev: Event):
    """祝福闪光 - 查看我的祝福闪光收集矩阵"""
    match = _BLESSING_RE.match((ev.text or "").strip() or (ev.raw_text or "").strip())
    page = int(match.group(1)) if (match and match.group(1)) else 1

    user = await require_user(bot, ev)
    if user is None:
        return

    data = await load_cached_data(USER_DATA_PATH, user.openid, logger)
    if not data:
        await send_niki_notify(bot, ev, CommonMsg.not_logged_in(True))
        return

    if not (data.get("journal_data", {}).get("state", {}).get("magicBallData")):
        await send_niki_notify(bot, ev, "祝福闪光数据尚未缓存, 请先发送 nk刷新 更新数据")
        return

    page_label = f"第 {page} 页" if page > 1 else ""
    await bot.send(
        f"[无限暖暖] 正在生成祝福闪光卡片{page_label}...",
        at_sender=bool(ev.group_id),
    )

    uid = user.uid or user.openid
    user_dir = USER_DATA_PATH / uid
    max_width = float(NikiConfig.get_config("NikiRenderScale").data)

    image_bytes = await render_blessing_card(
        data=data.get("journal_data", {}),
        login_info=data.get("login_info"),
        get_user_dir_fn=lambda _uid: user_dir,
        render_fn=lambda html: render_html_to_image(html, user_data_dir=user_dir, max_width=max_width),
        page=page,
    )

    if image_bytes:
        await bot.send(MessageSegment.image(image_bytes))
    else:
        await send_niki_notify(bot, ev, CardMsg.LOAD_FAILED)
