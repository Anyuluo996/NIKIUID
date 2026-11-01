"""NIKIUID 卡片 / 抽卡命令。

- niki卡片 / nk卡片 / nkkp - 生成奇想手账卡片
- niki抽卡 / nk抽卡 / nkck - 共鸣衣橱·杂志典藏名录(单版面不翻页; 参数:全/4/5)
- nk抽卡详情 / nkck详情 - 共鸣衣橱·横幅详情(单件图标+抽数角标, 支持页码)
- nk抽卡页面 / nkck页面 - 生成 10 分钟有效的临时网页(全部套装抽取数据+分享图)
- 紧凑抽卡命令(nkck限定5星)走 on_regex 监听
"""

from __future__ import annotations

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment

from ..utils.msgs import CardMsg, CommonMsg, send_niki_notify
from ..utils.cache import TimedCache  # noqa: F401  (保留给后续扩展)
from ..utils.parser import (
    CommandParseError,
    parse_gacha_args_text,
    parse_prefixed_command,
    build_gacha_parse_error_message,
)
from ..utils.session import require_user
from ..utils.render_image import render_html_to_image
from ..utils.storage_cache import load_cached_data
from ..niki_config.niki_config import NikiConfig
from ..utils.render_journal_card import render_journal_card
from ..utils.render_wardrobe_card import render_wardrobe_card
from ..niki_gacha_page.page_router import create_gacha_page
from ..utils.resource.RESOURCE_PATH import USER_DATA_PATH

sv_niki_card = SV("niki卡片")
sv_niki_gacha = SV("niki抽卡")

# 各模板每页套装数: 杂志名录单版面渲染(不翻页, 4列排到底), 横幅详情较占高度
_PAGE_SIZE_COUTURE = 999
_PAGE_SIZE_BANNER = 8

_GACHA_KINDS = ("gacha", "gacha_detail", "gacha_page")


async def _get_user_data_dir(uid: str) -> "object":
    """获取用户数据目录(USER_DATA_PATH/{uid})。"""
    user_dir = USER_DATA_PATH / uid
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


@sv_niki_card.on_command(("卡片", "kp"), block=True)
async def niki_card_cmd(bot: Bot, ev: Event):
    """niki卡片 - 查看奇想手账"""
    user = await require_user(bot, ev)
    if user is None:
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
    - 详情 - 横幅详情视图(单件图标+抽数)
    - 页面/网页 - 生成 10 分钟有效的临时网页
    - 第N页/pN - 页码
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
    """抽卡命令统一处理(抽卡/抽卡详情/抽卡页面)。"""
    try:
        # on_command 路径 args_text 无前缀(解析器返回 None), on_regex 路径带前缀
        parsed = parse_prefixed_command(args_text) or parse_gacha_args_text(args_text)
    except CommandParseError:
        await send_niki_notify(bot, ev, build_gacha_parse_error_message())
        return

    if parsed is None or parsed.kind not in _GACHA_KINDS:
        await send_niki_notify(bot, ev, build_gacha_parse_error_message())
        return

    if parsed.kind == "gacha_page":
        await _handle_gacha_page(bot, ev)
        return

    user = await require_user(bot, ev)
    if user is None:
        return

    data = await load_cached_data(USER_DATA_PATH, user.openid, logger)
    if not data:
        await send_niki_notify(bot, ev, CommonMsg.not_logged_in(True))
        return

    if parsed.kind == "gacha_detail":
        action, template_name, page_size = "详情", "wardrobe_banner_dark.html", _PAGE_SIZE_BANNER
        filter_mode = parsed.filter_mode
    else:
        # 杂志名录单版面渲染:默认展示抽到的套装(未抽齐的也显示), 传"全"看含未抽取的全部
        action, template_name, page_size = "卡片", "wardrobe_couture.html", _PAGE_SIZE_COUTURE
        filter_mode = parsed.filter_mode

    scope = {
        "drawn": "抽到的套装",
        "owned": "已共鸣套装",
        "all": "全部套装",
    }.get(filter_mode, "抽到的套装")
    page_label = f"第 {parsed.page} 页" if parsed.page > 1 else ""
    await bot.send(
        f"[无限暖暖] 正在生成共鸣衣橱{action}({scope}){page_label}...",
        at_sender=bool(ev.group_id),
    )

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
        filter_mode=filter_mode,
        page=parsed.page,
        page_size=page_size,
        template_name=template_name,
    )

    if image_bytes:
        await bot.send(MessageSegment.image(image_bytes))
    else:
        await send_niki_notify(bot, ev, CardMsg.LOAD_FAILED)


async def _handle_gacha_page(bot: Bot, ev: Event) -> None:
    """抽卡页面 - 生成 10 分钟内有效的临时网页链接。"""
    user = await require_user(bot, ev)
    if user is None:
        return

    data = await load_cached_data(USER_DATA_PATH, user.openid, logger)
    if not data:
        await send_niki_notify(bot, ev, CommonMsg.not_logged_in(True))
        return

    await bot.send("[无限暖暖] 正在生成抽卡页面...", at_sender=bool(ev.group_id))

    uid = user.uid or user.openid
    ok, msg = await create_gacha_page(
        data=data.get("journal_data", {}),
        login_info=data.get("login_info"),
        get_user_dir_fn=lambda _uid: USER_DATA_PATH / uid,
    )
    if ok:
        await bot.send(f"[无限暖暖] {msg}", at_sender=bool(ev.group_id))
    else:
        await send_niki_notify(bot, ev, msg)
