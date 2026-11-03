"""NIKIUID 资源预热命令。

- niki下载资源 / nk下载资源 / nkxzzy - 批量预下载渲染所需素材
  (套装预览图 / 单件图标 / 祝福闪光球图标与预览图),
  并顺带生成抽卡页面用的 WebP 压缩缓存
- 已存在的文件自动跳过; 首次全量下载数百到上千张, 分块并发拉取,
  避免首次「抽卡/详情/页面」渲染时边渲染边下载卡数分钟
"""

from __future__ import annotations

import time
import asyncio

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event

from ..utils.msgs import CommonMsg, send_niki_notify
from ..utils.session import require_user
from ..utils.storage_cache import load_cached_data
from ..utils.render_blessing_card import BLESSING_ASSETS_DIR
from ..utils.render_wardrobe_card import (
    SUITS_DIR,
    CLOTHS_DIR,
    collect_render_resource_urls,
)
from ..utils.resource.RESOURCE_PATH import USER_DATA_PATH
from ..utils.services.image_service import (
    WEBP_SUITS_DIR,
    WEBP_CLOTHS_DIR,
    png_name_of_url,
    bulk_convert_webp,
)
from ..utils.services.blessing_service import (
    bulk_download_icons,
    build_blessing_matrix,
    collect_blessing_icons,
)

sv_niki_resource = SV("niki资源")


@sv_niki_resource.on_command(("下载资源", "xzzy"), block=True)
async def niki_download_resources_cmd(bot: Bot, ev: Event):
    """niki下载资源 - 预热渲染所需的全部图片素材"""
    user = await require_user(bot, ev)
    if user is None:
        return

    data = await load_cached_data(USER_DATA_PATH, user.openid, logger)
    if not data:
        await send_niki_notify(bot, ev, CommonMsg.not_logged_in(True))
        return

    state = data.get("journal_data", {}).get("state", {})
    suit_urls, cloth_urls = collect_render_resource_urls(state)

    blessing_urls: list[str] = []
    magic_ball = state.get("magicBallData")
    if magic_ball:
        matrix = build_blessing_matrix(
            magic_ball.get("magicBallSuitList", []),
            magic_ball.get("magicBallItemList", []),
            magic_ball.get("magicBallColorList", []),
            state.get("magicBallList", []),
        )
        blessing_urls = collect_blessing_icons(matrix)

    total = len(set(suit_urls) | set(cloth_urls) | set(blessing_urls))
    if total == 0:
        await send_niki_notify(bot, ev, "暂无可下载的资源, 请先发送 nk刷新 更新数据")
        return

    await bot.send(
        f"[无限暖暖] 开始下载渲染资源, 共 {total} 张(已缓存的自动跳过), 首次全量下载需要几分钟, 完成后通知你...",
        at_sender=bool(ev.group_id),
    )

    t0 = time.monotonic()
    await asyncio.gather(
        bulk_download_icons(cloth_urls, CLOTHS_DIR),
        bulk_download_icons(suit_urls, SUITS_DIR),
        bulk_download_icons(blessing_urls, BLESSING_ASSETS_DIR),
        # 顺带预热 WebP 压缩缓存(抽卡页面用), 原图转一次即可
        bulk_convert_webp([png_name_of_url(u) for u in cloth_urls], CLOTHS_DIR, WEBP_CLOTHS_DIR),
        bulk_convert_webp([png_name_of_url(u) for u in suit_urls], SUITS_DIR, WEBP_SUITS_DIR),
    )
    elapsed = round(time.monotonic() - t0, 1)
    logger.info(f"[niki资源] 预热完成: {total} 张, 耗时 {elapsed}s")
    await send_niki_notify(
        bot,
        ev,
        f"资源下载完成(共 {total} 张, 耗时 {elapsed} 秒), 后续抽卡/详情/页面渲染不再卡顿",
    )
