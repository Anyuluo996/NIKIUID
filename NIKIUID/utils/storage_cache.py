"""用户缓存数据管理

奇想手账 JSON 数据存 DB 表(NikiJournalData),按 openid 索引查询,
替代原来的全目录文件扫描。头像等二进制资源仍存文件。
"""

import json
import re
from pathlib import Path
from typing import Any

from sqlmodel import Field, col, select
from sqlalchemy.ext.asyncio import AsyncSession

from gsuid_core.logger import logger
from gsuid_core.utils.database.base_models import BaseIDModel, with_session

# 用户目录名(uid/openid)只允许字母数字下划线短横线,杜绝 ../ 路径穿越
_SAFE_UID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class NikiJournalData(BaseIDModel, table=True):
    """奇想手账缓存数据,一行 = 一个 openid 的完整 JSON 快照。"""

    __table_args__: dict[str, Any] = {"extend_existing": True}

    openid: str = Field(default="", title="暖纸passport nid", index=True)
    uid: str = Field(default="", title="游戏角色UID", index=True)
    data: str = Field(default="{}", title="完整 JSON 数据")

    @classmethod
    @with_session
    async def get_by_openid(
        cls,
        session: AsyncSession,
        openid: str,
    ) -> "NikiJournalData | None":
        result = await session.execute(
            select(cls).where(cls.openid == openid).limit(1)
        )
        return result.scalars().first()

    @classmethod
    @with_session
    async def upsert(
        cls,
        session: AsyncSession,
        openid: str,
        uid: str,
        data_json: str,
    ) -> None:
        """按 openid 插入或更新。"""
        result = await session.execute(
            select(cls).where(cls.openid == openid).limit(1)
        )
        row = result.scalars().first()
        if row is None:
            row = cls(openid=openid, uid=uid, data=data_json)
            session.add(row)
        else:
            row.uid = uid
            row.data = data_json


def _default_logger():
    return logger


def get_user_dir(plugin_data_dir: Path, uid: str, create: bool = False) -> Path:
    """获取用户数据目录(用于头像等二进制资源文件)。

    Args:
        plugin_data_dir: 插件数据目录
        uid: 用户ID（应该是游戏UID，不是platform_user_id）
        create: 是否创建目录（默认不创建）

    Returns:
        用户数据目录路径

    Raises:
        ValueError: uid 含非法字符(路径穿越防护)
    """
    if not uid or not _SAFE_UID_RE.match(str(uid)):
        raise ValueError(f"非法 uid,拒绝路径构造: {uid!r}")
    user_dir = plugin_data_dir / str(uid)
    # 二次校验:resolve 后必须仍在 plugin_data_dir 之下
    if not user_dir.resolve().is_relative_to(plugin_data_dir.resolve()):
        raise ValueError(f"uid 导致路径越界,拒绝: {uid!r}")
    if create:
        user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


async def load_cached_data(
    plugin_data_dir: Path,
    platform_user_id: str,
    log=None,
) -> dict | None:
    """从 DB 加载用户数据(按 openid 索引,O(1) 查询)。

    Args:
        plugin_data_dir: 插件数据目录(保留兼容,头像等文件仍用)
        platform_user_id: 实际是 openid(登录时存入)
        log: 日志记录器

    Returns:
        用户数据字典，未找到返回 None
    """
    lg = log or _default_logger()
    if not platform_user_id:
        return None

    try:
        row = await NikiJournalData.get_by_openid(platform_user_id)
        if row is None:
            return None
        return json.loads(row.data) if row.data else None
    except Exception as e:
        lg.error(f"加载缓存数据失败: {e}")
        return None


async def save_cached_data(
    plugin_data_dir: Path,
    uid: str,
    platform_user_id: str,
    data: dict,
    log=None,
) -> None:
    """保存用户数据到 DB(按 openid upsert)。

    Args:
        plugin_data_dir: 插件数据目录(保留兼容)
        uid: 游戏搭配师编号
        platform_user_id: 实际是 openid
        data: 用户数据
        log: 日志记录器
    """
    lg = log or _default_logger()

    # 验证uid是游戏UID而不是platform_user_id
    if uid == platform_user_id:
        lg.error(
            f"错误：uid ({uid}) 与 platform_user_id ({platform_user_id}) 相同，"
            f"请检查是否传入了正确的游戏UID！"
        )
        return

    data["platform_user_id"] = platform_user_id

    try:
        await NikiJournalData.upsert(
            openid=platform_user_id,
            uid=uid,
            data_json=json.dumps(data, ensure_ascii=False),
        )
        lg.info(f"数据已保存到 DB: openid={platform_user_id[:8]}*** uid={uid}")
    except Exception as e:
        lg.error(f"保存缓存数据失败: {e}")
