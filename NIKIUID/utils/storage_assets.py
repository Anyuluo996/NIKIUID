"""套装图片下载工具"""

from pathlib import Path
from typing import Any

import aiohttp

from gsuid_core.logger import logger as _gscore_logger


class Logger(Any if False else object):
    """兼容占位:实际统一用 gsuid_core.logger"""
    pass


def _default_logger():
    return _gscore_logger


async def download_suit_images(
    suit_card_list: list,
    images_dir: Path,
    fix_fn=None,
    log=_gscore_logger,
) -> dict[str, str]:
    """下载套装图片到本地

    Args:
        suit_card_list: 套装数据列表
        images_dir: 图片存储目录
        fix_fn: 编码修复函数
        logger: 日志记录器

    Returns:
        套装名称到本地图片路径的映射
    """
    log = logger or _default_logger()
    if fix_fn is None:
        from .encoding import fix_encoding

        fix_fn = fix_encoding

    suits_dir = images_dir / "suits"
    suits_dir.mkdir(parents=True, exist_ok=True)

    name_to_path: dict[str, str] = {}

    async with aiohttp.ClientSession() as session:
        for card in suit_card_list:
            try:
                name_list = card.get("name", [])
                sub_suit = name_list[0].get("text", "") if name_list else ""
                if sub_suit:
                    sub_suit = fix_fn(sub_suit)
                else:
                    continue

                preview_image = card.get("preview_image", "")
                if not preview_image:
                    continue

                url_filename = preview_image.split("/")[-1]
                if not url_filename.endswith(".png"):
                    url_filename += ".png"
                local_path = suits_dir / url_filename

                if local_path.exists():
                    name_to_path[sub_suit] = str(local_path)
                    continue

                async with session.get(preview_image) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        with open(local_path, "wb") as f:
                            f.write(content)
                        name_to_path[sub_suit] = str(local_path)
                        log.info(f"下载套装图片: {sub_suit}")
            except Exception as e:
                log.warning(f"下载套装图片失败: {e}")
                continue

    log.info(f"共下载 {len(name_to_path)} 个套装图片")
    return name_to_path
