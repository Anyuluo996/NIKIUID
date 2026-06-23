"""NIKIUID 帮助图片渲染。

参考 NTEUID/nte_help/get_help.py,使用 gsuid_core 的 PIL 帮助框架
(draw_new_plugin_help.get_new_help) 渲染图片。图标用 D:\app\niki\bg\图标_抠图
下的无限暖暖主题素材(已按指令名重命名后放到 icon_path/)。
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from gsuid_core.help import draw_new_plugin_help as _help_framework
from gsuid_core.help.draw_new_plugin_help import get_new_help
from gsuid_core.help.model import PluginHelp

# 帮助图含精细图标和文字,默认 quality=85 双重 JPEG 压缩会糊。
# 拉到 100 让框架保存时尽量无损(仍 JPEG,但几乎无压缩痕迹)。
_help_framework.pic_quality = 100

from ..version import __version__ as NIKIUID_version

ICON = Path(__file__).parent.parent.parent / "ICON.png"
HELP_DATA = Path(__file__).parent / "help.json"
ICON_PATH = Path(__file__).parent / "icon_path"
TEXT_PATH = Path(__file__).parent / "texture2d"


def get_help_data() -> dict[str, PluginHelp]:
    with open(HELP_DATA, "r", encoding="utf-8") as file:
        return json.load(file)


plugin_help = get_help_data()


def _maybe(name: str) -> Image.Image | None:
    """`texture2d/{name}` 在则用、缺则回退到 gsuid_core help 框架的 dark 默认贴图。"""
    path = TEXT_PATH / name
    return Image.open(path) if path.exists() else None


async def get_help(pm: int):
    """渲染 NIKIUID 帮助图片。

    Args:
        pm: 调用者权限等级,用于过滤带 "pm" 字段的分类(主人功能)
    """
    return await get_new_help(
        plugin_name="NIKIUID",
        plugin_info={f"v{NIKIUID_version}": ""},
        plugin_icon=Image.open(ICON),
        plugin_help=plugin_help,
        plugin_prefix="niki / nk",
        help_mode="light",
        banner_bg=_maybe("banner_bg.jpg"),
        banner_sub_text="每一刻,都值得被珍藏。",
        help_bg=_maybe("bg.jpg"),
        cag_bg=_maybe("cag_bg.png"),
        item_bg=_maybe("item.png"),
        icon_path=ICON_PATH,
        footer=None,  # None 时回退到 gsuid_core 内置 footer
        enable_cache=False,
        column=4,
        pm=pm,
    )
