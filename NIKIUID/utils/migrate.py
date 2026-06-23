"""旧文件缓存 → DB 自动迁移

bot 启动时检查 USER_DATA_PATH 下是否有旧的 {uid}/data.json 文件,
有的话自动导入 NikiJournalData 表,导入完成后标记文件已迁移(加 .migrated 后缀),
不删除原文件(保留兜底)。

迁移幂等:已 .migrated 的文件不会重复导入;DB 里已有该 openid 的也会跳过。
"""

from __future__ import annotations

import json
from pathlib import Path

from gsuid_core.logger import logger

from .resource.RESOURCE_PATH import USER_DATA_PATH
from .storage_cache import NikiJournalData


_MIGRATED_SUFFIX = ".migrated"


async def migrate_file_cache_to_db() -> int:
    """扫描 USER_DATA_PATH 下的旧 data.json,迁移到 NikiJournalData 表。

    Returns:
        成功迁移的文件数
    """
    if not USER_DATA_PATH.exists():
        return 0

    migrated = 0
    skipped = 0
    failed = 0

    for user_dir in USER_DATA_PATH.iterdir():
        if not user_dir.is_dir():
            continue

        data_file = user_dir / "data.json"
        if not data_file.exists():
            continue

        # 已迁移过的跳过
        if (user_dir / "data.json.migrated").exists():
            skipped += 1
            continue

        try:
            with open(data_file, encoding="utf-8") as f:
                data = json.load(f)

            # 旧文件里 platform_user_id 字段存的是 openid
            openid = data.get("platform_user_id") or data.get("login_info", {}).get(
                "openid", ""
            )
            uid = data.get("login_info", {}).get("user_info", {}).get("role", {}).get(
                "uid", ""
            ) or user_dir.name

            if not openid:
                logger.warning(f"[迁移] 跳过 {user_dir.name}: 无 openid")
                # 标记为已处理,避免反复尝试
                _mark_migrated(data_file)
                skipped += 1
                continue

            # DB 里已有该 openid 就跳过(幂等)
            existing = await NikiJournalData.get_by_openid(openid)
            if existing is not None:
                logger.debug(f"[迁移] 跳过 {user_dir.name}: openid={openid[:8]}*** 已在 DB")
                _mark_migrated(data_file)
                skipped += 1
                continue

            # 写入 DB
            await NikiJournalData(
                openid=openid,
                uid=str(uid),
                data=json.dumps(data, ensure_ascii=False),
            ).insert_data()

            _mark_migrated(data_file)
            migrated += 1
            logger.info(
                f"[迁移] {user_dir.name} → DB: openid={openid[:8]}*** uid={uid}"
            )

        except json.JSONDecodeError as e:
            logger.warning(f"[迁移] {user_dir.name}/data.json 解析失败: {e}")
            failed += 1
        except Exception as e:
            logger.warning(f"[迁移] {user_dir.name} 迁移异常: {e}")
            failed += 1

    if migrated or skipped or failed:
        logger.info(
            f"[迁移] 文件缓存→DB 完成: 迁移 {migrated} 条,跳过 {skipped} 条,"
            f"失败 {failed} 条"
        )
    return migrated


def _mark_migrated(data_file: Path) -> None:
    """标记文件已迁移(创建空 .migrated 标记,不删原文件)。"""
    marker = data_file.with_suffix(data_file.suffix + _MIGRATED_SUFFIX)
    try:
        marker.touch()
    except OSError:
        pass
