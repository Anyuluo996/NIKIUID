"""套装图片下载工具

复用 gsuid_core 内置的 download() 函数(httpx + aiofiles,带超时和日志),
替代原来手写的 aiohttp + 同步 open() 下载循环。
"""

from pathlib import Path

from gsuid_core.logger import logger as _gscore_logger
from gsuid_core.utils.download_resource.download_file import download


def _default_logger():
    return _gscore_logger


async def download_suit_images(
    suit_card_list: list,
    images_dir: Path,
    fix_fn=None,
    log=_gscore_logger,
    limit: int = 50,
) -> dict[str, str]:
    """下载共鸣套装预览图。

    Args:
        suit_card_list: 共鸣套装列表,每项含 preview_image / suit_id
        images_dir: 图片保存目录
        fix_fn: 编码修正函数(可选)
        log: 日志记录器
        limit: 最多下载数量(防止一次性下载太多)

    Returns:
        {suit_id: 本地文件名} 映射
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    name_to_path: dict[str, str] = {}
    count = 0

    for card in suit_card_list:
        if count >= limit:
            break
        if not isinstance(card, dict):
            continue

        preview_image = card.get("preview_image", "")
        suit_id = card.get("suit_id", "")
        if not preview_image or not suit_id:
            continue

        # URL 文件名(与 render_wardrobe_card 的推导保持一致)
        url_filename = preview_image.split("/")[-1]
        if fix_fn:
            url_filename = fix_fn(url_filename)

        # 本地文件名统一用 .png
        local_name = url_filename.rsplit(".", 1)[0] + ".png"
        local_path = images_dir / local_name

        # 已存在就跳过
        if local_path.exists():
            name_to_path[suit_id] = local_name
            continue

        try:
            retcode = await download(
                preview_image,
                images_dir,
                local_name,
                tag="[NIKI]",
            )
            if retcode == 200:
                name_to_path[suit_id] = local_name
                count += 1
            else:
                log.warning(f"套装 {suit_id} 下载失败: HTTP {retcode}")
        except Exception as e:
            log.warning(f"套装 {suit_id} 下载异常: {e}")

    log.info(f"[NIKI] 套装图片下载完成: {len(name_to_path)} 张")
    return name_to_path
