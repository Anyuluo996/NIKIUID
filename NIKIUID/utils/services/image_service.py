"""图标压缩服务: PNG 原图 → WebP 页面资产。

抽卡页面的套装预览原图平均 630KB(最大 7.8MB), 一页全量 100+MB 会
打穿反代/CDN 回源(524/525/HTTP2 协议错误)。页面实际显示尺寸只有
64~118px(分享图 2x DPR 约 236px), 转 WebP(max 256px, q80)后单张
降到几 KB~几十 KB。PNG 原图保留不动, 供 pytakumi 图片渲染管线使用。
"""

from __future__ import annotations

import asyncio
from typing import Any
from pathlib import Path

from PIL import Image

from gsuid_core.logger import logger

from ..resource.RESOURCE_PATH import USER_DATA_PATH

# 页面最大显示 118px, 分享图 2x DPR → 236px, 256 留足余量
WEBP_MAX_SIDE = 256
WEBP_QUALITY = 80
_CONVERT_WORKERS = 8

# WebP 压缩缓存目录(与 PNG 原图目录分离, 文件名一一对应 xxx.png → xxx.webp)
WEBP_SUITS_DIR = USER_DATA_PATH / "webp" / "suits"
WEBP_CLOTHS_DIR = USER_DATA_PATH / "webp" / "cloths"


def png_name_of_url(url: str) -> str:
    """远程图标 URL → 本地 PNG 缓存文件名(与 download_blessing_icons 同规则)。"""
    fname = url.split("/")[-1]
    if not fname.endswith(".png"):
        fname += ".png"
    return fname


def webp_name(fname: str) -> str:
    """PNG 文件名 → WebP 资产名(xxx.png → xxx.webp)。"""
    return fname[:-4] + ".webp" if fname.endswith(".png") else fname + ".webp"


def convert_png_to_webp(
    src: Path,
    dst: Path,
    max_side: int = WEBP_MAX_SIDE,
    quality: int = WEBP_QUALITY,
) -> bool:
    """单张 PNG → WebP(等比缩到 max_side 内, 保留透明通道)。

    dst 已存在且不旧于 src 时直接复用; 源缺失/损坏返回 False。
    """
    if not src.is_file():
        return False
    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
        return True
    try:
        with Image.open(src) as im:
            im = im.convert("RGBA")
            if max(im.size) > max_side:
                im.thumbnail((max_side, max_side), Image.LANCZOS)
            dst.parent.mkdir(parents=True, exist_ok=True)
            im.save(dst, "WEBP", quality=quality, method=4)
        return True
    except Exception as e:
        logger.warning(f"[image] WebP 转换失败 {src.name}: {e}")
        return False


async def bulk_convert_webp(
    png_names: list[str],
    src_dir: Path,
    dst_dir: Path,
    concurrency: int = _CONVERT_WORKERS,
    log: Any = logger,
) -> None:
    """并发批量转换(去重; 已存在且新鲜的秒回)。CPU 密集, 丢线程池执行。"""
    names = [n for n in dict.fromkeys(png_names) if n]
    if not names:
        return
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def _one(name: str) -> None:
        nonlocal done
        src = src_dir / name
        if not src.is_file():
            return
        async with sem:
            ok = await loop.run_in_executor(
                None, convert_png_to_webp, src, dst_dir / webp_name(name)
            )
        if ok:
            done += 1

    await asyncio.gather(*(_one(n) for n in names))
    log.info(f"[image] WebP 转换: {done}/{len(names)} ({src_dir.name})")
