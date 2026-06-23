"""NIKIUID 数据库模型。

一行 = 一个聊天用户(user_id × bot_id)绑定的一个无限暖暖账号(openid)。
无限暖暖一个 passport 账号对应一个游戏角色(uid),不涉及多游戏多角色,
所以表结构比 NTE 简单:用 openid 作为账号去重键,uid 作为角色标识。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar

from sqlmodel import Field, col, select
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from gsuid_core.logger import logger
from gsuid_core.utils.database.startup import exec_list
from gsuid_core.utils.database.base_models import BaseIDModel, with_session

exec_list.extend(
    [
        "CREATE INDEX IF NOT EXISTS ix_nikiuser_uid ON nikiuser (uid)",
        "CREATE INDEX IF NOT EXISTS ix_nikiuser_user_id ON nikiuser (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_nikiuser_openid ON nikiuser (openid)",
    ]
)

T_NikiUser = TypeVar("T_NikiUser", bound="NikiUser")


class NikiUser(BaseIDModel, table=True):
    """一行 = 一个聊天用户绑定的一个无限暖暖账号。

    用 (user_id, bot_id, openid) 唯一标识一个账号。
    `cookie` 字段复用基类语义存 access token;这里额外用 `token` / `openid`
    做语义化字段,方便和 passport 返回的 dict 对齐。
    """

    __table_args__: dict[str, Any] = {"extend_existing": True}

    user_id: str = Field(default="", title="聊天平台用户ID", index=True)
    bot_id: str = Field(default="", title="机器人ID")
    uid: str = Field(default="", title="游戏角色UID", index=True)
    openid: str = Field(default="", title="暖纸passport nid", index=True)
    token: str = Field(default="", title="访问token")
    nickname: str = Field(default="", title="搭配师昵称")
    level: int = Field(default=0, title="搭配师等级")
    device_id: str = Field(default="", title="设备ID")
    client_id: int = Field(default=1106, title="MYL client_id")
    area_id: int = Field(default=1, title="区服ID")
    updated_at: datetime = Field(
        default_factory=datetime.now,
        sa_column_kwargs={"onupdate": datetime.now},
        title="更新时间",
    )

    @classmethod
    @with_session
    async def get_active(
        cls: type[T_NikiUser],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
    ) -> T_NikiUser | None:
        """取该聊天用户最新登录的一行;未登录返回 None。"""
        result = await session.execute(
            select(cls)
            .where(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                col(cls.openid) != "",
                col(cls.token) != "",
            )
            .order_by(col(cls.updated_at).desc())
            .limit(1)
        )
        return result.scalars().first()

    @classmethod
    @with_session
    async def save_token(
        cls: type[T_NikiUser],
        session: AsyncSession,
        *,
        user_id: str,
        bot_id: str,
        openid: str,
        token: str,
        uid: str = "",
        nickname: str = "",
        level: int = 0,
        device_id: str = "",
        client_id: int = 1106,
        area_id: int = 1,
    ) -> T_NikiUser:
        """登录/刷新后写入或更新一行。按 (user_id, bot_id, openid) upsert。"""
        result = await session.execute(
            select(cls).where(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                cls.openid == openid,
            )
        )
        row = result.scalars().first()
        now = datetime.now()
        if row is None:
            row = cls(
                user_id=user_id,
                bot_id=bot_id,
                openid=openid,
                token=token,
                uid=uid,
                nickname=nickname,
                level=level,
                device_id=device_id,
                client_id=client_id,
                area_id=area_id,
                updated_at=now,
            )
            session.add(row)
            logger.info(f"[NIKIUID] 新增账号 user_id={user_id} openid={openid[:8]}***")
        else:
            row.token = token
            if uid:
                row.uid = uid
            if nickname:
                row.nickname = nickname
            if level:
                row.level = level
            if device_id:
                row.device_id = device_id
            row.client_id = client_id
            row.area_id = area_id
            row.updated_at = now
        await session.commit()
        await session.refresh(row)
        return row

    @classmethod
    @with_session
    async def update_profile(
        cls: type[T_NikiUser],
        session: AsyncSession,
        *,
        user_id: str,
        bot_id: str,
        openid: str,
        uid: str = "",
        nickname: str = "",
        level: int = 0,
    ) -> bool:
        """刷新数据后回写展示字段(nickname/level/uid)。"""
        result = await session.execute(
            select(cls).where(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                cls.openid == openid,
            )
        )
        row = result.scalars().first()
        if row is None:
            return False
        if uid:
            row.uid = uid
        if nickname:
            row.nickname = nickname
        if level is not None:  # 允许合法的 0 级
            row.level = level
        row.updated_at = datetime.now()
        return True

    @classmethod
    @with_session
    async def list_accounts(
        cls: type[T_NikiUser],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
    ) -> list[T_NikiUser]:
        """列出该用户绑定的所有账号,按更新时间倒序。"""
        result = await session.execute(
            select(cls)
            .where(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                col(cls.openid) != "",
            )
            .order_by(col(cls.updated_at).desc())
        )
        return list(result.scalars().all())

    @classmethod
    @with_session
    async def delete_account(
        cls: type[T_NikiUser],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        openid: str,
    ) -> bool:
        """退出登录:删除指定 openid 的行。"""
        result = await session.execute(
            delete(cls).where(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                cls.openid == openid,
            )
        )
        return (result.rowcount or 0) > 0

    @classmethod
    @with_session
    async def delete_all(
        cls: type[T_NikiUser],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
    ) -> int:
        """全部登出:删除该用户所有账号。"""
        result = await session.execute(
            delete(cls).where(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
            )
        )
        return result.rowcount or 0

    @classmethod
    @with_session
    async def touch(
        cls: type[T_NikiUser],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        openid: str,
    ) -> None:
        """更新 updated_at 时间戳,用于"切换当前账号"。"""
        result = await session.execute(
            select(cls).where(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                cls.openid == openid,
            )
        )
        row = result.scalars().first()
        if row is not None:
            row.updated_at = datetime.now()
