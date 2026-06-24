"""NIKIUID 帮助命令。

渲染 PIL 帮助图片(参考 NTEUID/nte_help)。图标用无限暖暖主题抠图素材。
"""

from __future__ import annotations

from PIL import Image

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment
from gsuid_core.help.utils import register_help

from .get_help import ICON, get_help
from ..niki_config.prefix import niki_prefix

sv_niki_help = SV("niki帮助")


@sv_niki_help.on_fullmatch(("帮助", "bz", "help"), block=True)
async def niki_help_cmd(bot: Bot, ev: Event):
    """niki帮助 - 查看命令帮助(图片)"""
    img = await get_help(ev.user_pm)
    if img:
        await bot.send(MessageSegment.image(img))
    else:
        await bot.send("帮助图片渲染失败,请稍后再试")


# 注册到 gsuid_core 全局插件帮助一览(前缀跟随配置,不写死)
register_help("NIKIUID", f"{niki_prefix()}帮助", Image.open(ICON))
