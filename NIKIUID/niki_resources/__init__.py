"""NIKIUID 资源预热命令。

- niki下载资源 / nk下载资源 / nkxzzy - 批量预下载渲染所需素材
  (套装预览图 / 单件图标 / 祝福闪光球图标与预览图)
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
from ..utils.services.blessing_service import (
    build_blessing_matrix,
    collect_blessing_icons,
    download_blessing_icons,
)

sv_niki_resource = SV("niki资源")

# 分块并发: 每块内顺序下载, 块间并发, 控制对素材 CDN 的并发压力
_DOWNLOAD_CHUNK = 40
_DOWNLOAD_CONCURRENCY = 8


async def _bulk_download(urls: list[str], folder, tag: str) -> None:
    """分块并发下载(已缓存的文件由 download_blessing_icons 秒回)。"""
    urls = [u for u in dict.fromkeys(urls) if u]
    if not urls:
        return
    chunks = [urls[i:i + _DOWNLOAD_CHUNK] for i in range(0, len(urls), _DOWNLOAD_CHUNK)]

    async def _run(chunk: list[str]) -> None:
        try:
            await download_blessing_icons(chunk, folder)
        except Exception as e:
            logger.warning(f"[niki资源] {tag} 分块下载失败({len(chunk)} 张): {e}")

    await asyncio.gather(*(_run(c) for c in chunks))


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
        f"[无限暖暖] 开始下载渲染资源, 共 {total} 张(已缓存的自动跳过), "
        "首次全量下载需要几分钟, 完成后通知你...",
        at_sender=bool(ev.group_id),
    )

    t0 = time.monotonic()
    await asyncio.gather(
        _bulk_download(cloth_urls, CLOTHS_DIR, "单件图标"),
        _bulk_download(suit_urls, SUITS_DIR, "套装预览图"),
        _bulk_download(blessing_urls, BLESSING_ASSETS_DIR, "祝福闪光素材"),
    )
    elapsed = round(time.monotonic() - t0, 1)
    logger.info(f"[niki资源] 预热完成: {total} 张, 耗时 {elapsed}s")
    await send_niki_notify(
        bot, ev,
        f"资源下载完成(共 {total} 张, 耗时 {elapsed} 秒), "
        "后续抽卡/详情/页面渲染不再卡顿",
    )
