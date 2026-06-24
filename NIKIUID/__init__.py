import asyncio

from gsuid_core.sv import Plugins
from gsuid_core.gss import gss
from gsuid_core.logger import logger

Plugins(
    name="NIKIUID",
    force_prefix=["niki", "nk"],
    allow_empty_prefix=False,
)


@gss.on_bot_connect
async def niki_migrate_on_startup():
    """bot 启动时自动迁移旧的文件缓存到 DB。

    幂等:已迁移的文件会跳过,DB 里已有 openid 的也会跳过。
    失败的文件保留原样,下次启动再试。
    """
    await asyncio.sleep(3)  # 等 DB 引擎初始化完成
    try:
        from .utils.migrate import migrate_file_cache_to_db

        count = await migrate_file_cache_to_db()
        if count > 0:
            logger.success(f"[NIKIUID] 自动迁移完成: {count} 条文件缓存已导入 DB")
    except Exception as e:
        logger.warning(f"[NIKIUID] 自动迁移失败: {e}")
