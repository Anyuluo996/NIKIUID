"""NIKIUID 卡片 / 抽卡命令。

- niki卡片 / nk卡片 / nkkp - 生成奇想手账卡片
- niki抽卡 / nk抽卡 / nkck - 生成共鸣衣橱卡片(支持参数:全/4/5/统计/记录)
- 紧凑抽卡命令(nkck限定5星)走 on_regex 监听
"""

from __future__ import annotations

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment
from gsuid_core.sv import SV

from ..niki_config.niki_config import NikiConfig
from ..utils.cache import TimedCache  # noqa: F401  (保留给后续扩展)
from ..utils.database import NikiUser
from ..utils.msgs import CardMsg, CommonMsg, send_niki_notify
from ..utils.parser import (
    CommandParseError,
    build_gacha_parse_error_message,
    parse_gacha_args_text,
)
from ..utils.render_image import render_html_to_image
from ..utils.render_journal_card import render_journal_card
from ..utils.render_wardrobe_card import render_wardrobe_card
from ..utils.resource.RESOURCE_PATH import USER_DATA_PATH
from ..utils.storage_cache import load_cached_data

sv_niki_card = SV("niki卡片")
sv_niki_gacha = SV("niki抽卡")


async def _get_user_data_dir(uid: str) -> "object":
    """获取用户数据目录(USER_DATA_PATH/{uid})。"""
    user_dir = USER_DATA_PATH / uid
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


@sv_niki_card.on_command(("卡片", "kp"), block=True)
async def niki_card_cmd(bot: Bot, ev: Event):
    """niki卡片 - 查看奇想手账"""
    user = await NikiUser.get_active(ev.user_id, ev.bot_id)
    if user is None:
        accounts = await NikiUser.list_accounts(ev.user_id, ev.bot_id)
        await send_niki_notify(bot, ev, CommonMsg.not_logged_in(bool(accounts)))
        return

    # 用 openid(原 platform_user_id)查找缓存数据
    data = await load_cached_data(USER_DATA_PATH, user.openid, logger)
    if not data:
        await send_niki_notify(bot, ev, CommonMsg.not_logged_in(True))
        return

    await bot.send(f"[无限暖暖] {CardMsg.REFRESHING}", at_sender=bool(ev.group_id))

    uid = user.uid or user.openid
    user_dir = USER_DATA_PATH / uid

    max_width = float(NikiConfig.get_config("NikiRenderScale").data)

    image_bytes = await render_journal_card(
        data=data.get("journal_data", {}),
        login_info=data.get("login_info"),
        map_data=data.get("map_data"),
        get_user_dir_fn=lambda _uid: user_dir,
        render_fn=lambda html: render_html_to_image(
            html, user_data_dir=user_dir, max_width=max_width
        ),
    )

    if image_bytes:
        await bot.send(MessageSegment.image(image_bytes))
    else:
        await send_niki_notify(bot, ev, CardMsg.LOAD_FAILED)


@sv_niki_gacha.on_command(("抽卡", "ck"), block=True)
async def niki_gacha_cmd(bot: Bot, ev: Event):
    """niki抽卡 [参数] - 查看共鸣衣橱

    参数(可选,可组合):
    - 全/all/a - 显示全部套装(默认只显示已共鸣)
    - 5/五/五星 - 五星(默认)
    - 4/四/四星 - 四星
    - 统计/tj - 统计视图(默认)
    - 记录/jl - 记录视图
    """
    await _handle_gacha(bot, ev, ev.text)


@sv_niki_gacha.on_regex(r"(?:抽卡|ck)\S+$", block=True)
async def niki_gacha_compact_cmd(bot: Bot, ev: Event):
    """紧凑抽卡命令:nkck限定5星 / niki抽卡全(无空格参数)。

    on_regex 命中后 ev.command 是正则匹配结果,ev.text 是命令后的剩余文本。
    这里直接复用 on_command 的处理逻辑,从 ev.raw_text 解析参数。
    """
    # on_regex 命中时 ev.text 可能为空,从 raw_text 重新解析
    raw = ev.raw_text or ""
    await _handle_gacha(bot, ev, raw)


async def _handle_gacha(bot: Bot, ev: Event, args_text: str) -> None:
    """抽卡命令统一处理。"""
    try:
        parsed = parse_gacha_args_text(args_text)
    except CommandParseError:
        await send_niki_notify(bot, ev, build_gacha_parse_error_message())
        return

    if parsed is None or parsed.kind != "gacha":
        await send_niki_notify(bot, ev, build_gacha_parse_error_message())
        return

    user = await NikiUser.get_active(ev.user_id, ev.bot_id)
    if user is None:
        accounts = await NikiUser.list_accounts(ev.user_id, ev.bot_id)
        await send_niki_notify(bot, ev, CommonMsg.not_logged_in(bool(accounts)))
        return

    data = await load_cached_data(USER_DATA_PATH, user.openid, logger)
    if not data:
        await send_niki_notify(bot, ev, CommonMsg.not_logged_in(True))
        return

    action = "已共鸣套装" if parsed.filter_mode == "owned" else "全部套装"
    await bot.send(f"[无限暖暖] 正在生成{action}卡片...", at_sender=bool(ev.group_id))

    uid = user.uid or user.openid
    user_dir = USER_DATA_PATH / uid
    max_width = float(NikiConfig.get_config("NikiRenderScale").data)

    image_bytes = await render_wardrobe_card(
        data=data.get("journal_data", {}),
        pool_type=parsed.pool_type,
        login_info=data.get("login_info"),
        get_user_dir_fn=lambda _uid: user_dir,
        render_fn=lambda html, _pool="", _num=0: render_html_to_image(
            html, user_data_dir=user_dir, max_width=max_width
        ),
        filter_mode=parsed.filter_mode,
    )

    if image_bytes:
        await bot.send(MessageSegment.image(image_bytes))
    else:
        await send_niki_notify(bot, ev, CardMsg.LOAD_FAILED)
