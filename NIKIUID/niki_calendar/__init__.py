"""日历命令 — 查看无限暖暖版本内容一览图片。

从 NIKIUID-calendar 仓库拉取 manifest.json,
展示指定版本的图片(活动日历/新套装/新玩法等)。

命令:
  nk日历          — 最新版本
  nk日历 2.7      — 指定版本
  nk日历 列表     — 列出所有可用版本
"""

from __future__ import annotations

import json
from pathlib import Path

import aiohttp

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment
from gsuid_core.sv import SV

from ..utils.resource.RESOURCE_PATH import USER_DATA_PATH

sv_niki_calendar = SV("niki日历")

# NIKIUID-calendar 仓库的 raw URL(CNB,中国可直连)
# GitHub 仓库(https://github.com/Anyuluo996/NIKIUID-calendar)也同步,但 CNB 在国内更快
CALENDAR_SLUG = "anyuluo/NIKIUID-calendar"
RAW_BASE = f"https://cnb.cool/{CALENDAR_SLUG}/-/git/raw/main"
MANIFEST_URL = f"{RAW_BASE}/manifest.json"

# 本地缓存目录
CACHE_DIR = USER_DATA_PATH / "calendar"


async def _fetch_manifest() -> dict | None:
    """拉取远程 manifest.json。"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                MANIFEST_URL, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"[niki日历] manifest 拉取失败: HTTP {resp.status}")
                    return None
                text = await resp.text()
                return json.loads(text)
    except Exception as e:
        logger.warning(f"[niki日历] manifest 拉取异常: {e}")
        return None


async def _download_image(version: str, filename: str) -> bytes | None:
    """下载单张图片,带本地缓存。"""
    local_path = CACHE_DIR / version / filename
    if local_path.exists() and local_path.stat().st_size > 0:
        return local_path.read_bytes()

    url = f"{RAW_BASE}/images/{version}/{filename}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"[niki日历] 图片下载失败 {filename}: HTTP {resp.status}")
                    return None
                data = await resp.read()

        # 写入缓存
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        return data
    except Exception as e:
        logger.warning(f"[niki日历] 图片下载异常 {filename}: {e}")
        return None


def _find_version(manifest: dict, query: str) -> dict | None:
    """从 manifest 找指定版本。支持精确匹配和模糊匹配。"""
    versions = manifest.get("versions", [])
    # 精确匹配
    for v in versions:
        if v["version"] == query:
            return v
    # 模糊匹配(包含)
    for v in versions:
        if query in v["version"]:
            return v
    return None


@sv_niki_calendar.on_fullmatch(("日历", "calendar", "rl"), block=True)
@sv_niki_calendar.on_command(("日历", "calendar", "rl"), block=True)
async def niki_calendar_cmd(bot: Bot, ev: Event):
    """nk日历 - 查看版本内容一览图片(活动日历/新套装/新玩法)"""
    query = ev.text.strip()

    # 拉取 manifest
    await bot.send("[无限暖暖] 正在获取日历数据...", at_sender=bool(ev.group_id))
    manifest = await _fetch_manifest()
    if not manifest:
        await bot.send("日历数据获取失败,请稍后重试")
        return

    versions = manifest.get("versions", [])

    # 列表模式
    if query in ("列表", "list", "所有", "全部", "all"):
        if not versions:
            await bot.send("暂无版本数据")
            return
        lines = ["📋 可用版本列表:\n"]
        for v in versions:
            img_count = len(v.get("images", []))
            lines.append(f"  v{v['version']} ({v.get('publish_date', '')}) — {img_count}图")
        lines.append(f"\n最新: v{manifest.get('latest_version', '?')}")
        lines.append("使用: nk日历 版本号(如 nk日历 2.7)")
        await bot.send("\n".join(lines))
        return

    # 确定要展示的版本
    if not query:
        # 默认最新
        version_data = versions[0] if versions else None
    else:
        version_data = _find_version(manifest, query)

    if version_data is None:
        available = ", ".join(v["version"] for v in versions[:8])
        await bot.send(f"未找到版本「{query}」,可用版本: {available}")
        return

    images = version_data.get("images", [])
    if not images:
        await bot.send(f"v{version_data['version']} 暂无图片内容")
        return

    # 下载并发送图片
    ver = version_data["version"]
    title = version_data.get("title", f"v{ver}")[:60]
    await bot.send(f"📅 {title}\n共 {len(images)} 张图片", at_sender=bool(ev.group_id))

    for img_info in images:
        filename = img_info["filename"]
        data = await _download_image(ver, filename)
        if data:
            await bot.send(MessageSegment.image(data))
        else:
            await bot.send(f"  ⚠️ 图片加载失败: {filename}")
