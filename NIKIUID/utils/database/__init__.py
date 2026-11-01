"""NIKIUID 数据库模型。

一行 = 一个聊天用户(user_id × bot_id)绑定的一个无限暖暖账号(openid)。

继承 GS Core 的 `User` 基类(而非 BaseIDModel),复用 cookie/status/user_id/bot_id
等标准字段和方法族。token 存在 `cookie` 字段(语义复用),openid/uid 是游戏特有字段。
"""

from __future__ import annotations

from typing import Any, TypeVar
from datetime import datetime

from sqlmodel import Field, col, select
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from gsuid_core.logger import logger
from gsuid_core.webconsole.mount_app import PageSchema, GsAdminModel, site
from gsuid_core.utils.database.startup import exec_list
from gsuid_core.utils.database.base_models import User, with_session

from ..auth.credential_store import decrypt_text, encrypt_text, mask_account

exec_list.extend(
    [
        "CREATE INDEX IF NOT EXISTS ix_nikiuser_uid ON nikiuser (uid)",
        "CREATE INDEX IF NOT EXISTS ix_nikiuser_openid ON nikiuser (openid)",
        "CREATE INDEX IF NOT EXISTS ix_nikicredential_uid ON nikicredential (user_id)",
        # ── schema 迁移:旧表(继承 BaseIDModel)→ 新表(继承 User) ──
        # User 基类新增的列,旧表不存在,用 ALTER TABLE ADD COLUMN 补上。
        # SQLite 的 ADD COLUMN 对已存在的列会报错,用 try-except 在 GS Core 层吞掉。
        # GS Core 的 exec_list 对失败语句只 warning 不中断,所以直接列即可。
        # 注意:SQLite 不支持 IF NOT EXISTS 语法给 ADD COLUMN,重复执行会 warning。
        "ALTER TABLE nikiuser ADD COLUMN cookie TEXT DEFAULT ''",
        "ALTER TABLE nikiuser ADD COLUMN stoken TEXT DEFAULT ''",
        "ALTER TABLE nikiuser ADD COLUMN status TEXT DEFAULT ''",
        "ALTER TABLE nikiuser ADD COLUMN push_switch INTEGER DEFAULT 0",
        "ALTER TABLE nikiuser ADD COLUMN sign_switch INTEGER DEFAULT 0",
        # 旧 token 列的数据迁移到 cookie(语义复用)
        # 仅在 cookie 为空且 token 有值时复制,避免覆盖新数据
        "UPDATE nikiuser SET cookie = token WHERE cookie = '' AND token IS NOT NULL AND token != ''",
        # 旧表 token 字段已废弃(token 现在是 property → cookie),保留列不删(SQLite 不支持 DROP COLUMN < 3.35)
    ]
)

T_NikiUser = TypeVar("T_NikiUser", bound="NikiUser")
T_NikiCredential = TypeVar("T_NikiCredential", bound="NikiCredential")


class NikiUser(User, table=True):
    """一行 = 一个聊天用户绑定的一个无限暖暖账号。

    继承 User 基类,复用:
    - user_id / bot_id(BaseModel 层提供,不在本类重复声明)
    - cookie:存 access token(语义复用)
    - status:token 状态("ok" / "expired" / None)
    - stoken:存 openid(语义复用,便于基类的 uid 查询方法使用)

    游戏特有字段:uid / nickname / level / device_id / client_id / area_id
    """

    __table_args__: dict[str, Any] = {"extend_existing": True}

    uid: str = Field(default="", title="游戏角色UID", index=True)
    openid: str = Field(default="", title="暖纸passport nid", index=True)
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

    @property
    def token(self) -> str:
        """access token(复用基类 cookie 字段)。"""
        return self.cookie or ""

    @token.setter
    def token(self, value: str) -> None:
        self.cookie = value or ""

    @classmethod
    @with_session
    async def get_active(
        cls: type[T_NikiUser],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
    ) -> T_NikiUser | None:
        """取该聊天用户最新登录的一行;未登录返回 None。

        过滤掉 token 失效(status="expired")的账号。
        """
        result = await session.execute(
            select(cls)
            .where(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                col(cls.openid) != "",
                col(cls.cookie) != "",
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
                cookie=token,
                stoken=openid,
                uid=uid,
                nickname=nickname,
                level=level if level is not None else 0,
                device_id=device_id,
                client_id=client_id,
                area_id=area_id,
                status="ok",
                updated_at=now,
            )
            session.add(row)
            logger.info(f"[NIKIUID] 新增账号 user_id={user_id} openid={openid[:8]}***")
        else:
            row.cookie = token
            row.stoken = openid
            row.status = "ok"
            if uid:
                row.uid = uid
            if nickname:
                row.nickname = nickname
            if level is not None:
                row.level = level
            if device_id:
                row.device_id = device_id
            row.client_id = client_id
            row.area_id = area_id
            row.updated_at = now
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

    @classmethod
    @with_session
    async def mark_expired(
        cls: type[T_NikiUser],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        openid: str,
    ) -> None:
        """标记 token 已失效(status="expired"),不删行。"""
        result = await session.execute(
            select(cls).where(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                cls.openid == openid,
            )
        )
        row = result.scalars().first()
        if row is not None:
            row.status = "expired"


@site.register_admin
class NikiUserAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(label="无限暖暖用户管理", icon="fa fa-users")  # type: ignore
    model = NikiUser


class NikiCredential(User, table=True):
    """一行 = 一个聊天用户保存的一组账号密码(用于自动登录)。

    account/password 均为 AES-256-GCM 强加密密文(逐行独立 nonce,
    密钥独立存放在 MAIN_PATH/credential.key, 不入库不入源码), 可逆;
    account_mask 为打码展示用明文。明文密码绝不入库、不写日志。
    """

    __table_args__: dict[str, Any] = {"extend_existing": True}

    account_enc: str = Field(default="", title="加密后的登录账号")
    password_enc: str = Field(default="", title="加密后的登录密码")
    # 旧"逐行盐"列: 强加密后 nonce 已并入密文, 列保留但不再使用(SQLite 不便删列)
    salt: str = Field(default="", title="已废弃(历史盐列)")
    account_mask: str = Field(default="", title="账号打码展示")
    updated_at: datetime = Field(
        default_factory=datetime.now,
        sa_column_kwargs={"onupdate": datetime.now},
        title="更新时间",
    )

    def reveal(self) -> tuple[str, str]:
        """还原 (账号, 密码) 明文。

        密文缺失/损坏/密钥不匹配时返回空对(不抛), 由调用方按
        "凭证损坏"回退网页登录;保存时的明文比对同样安全。
        """
        if not (self.account_enc and self.password_enc):
            return "", ""
        try:
            return decrypt_text(self.account_enc), decrypt_text(self.password_enc)
        except Exception:
            return "", ""

    @classmethod
    @with_session
    async def save_credential(
        cls: type[T_NikiCredential],
        session: AsyncSession,
        *,
        user_id: str,
        bot_id: str,
        account: str,
        password: str,
    ) -> T_NikiCredential:
        """保存/更新一组账号密码(按同一账号 upsert, 单用户最多留 5 组)。"""
        mask = mask_account(account)
        result = await session.execute(
            select(cls)
            .where(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                col(cls.account_enc) != "",
            )
            .order_by(col(cls.updated_at).desc())
        )
        rows = list(result.scalars().all())
        target = None
        for row in rows:
            if mask == row.account_mask:
                existing_account, _ = row.reveal()
                if existing_account == account:
                    target = row
                    break
        now = datetime.now()
        if target is not None:
            target.account_enc = encrypt_text(account)
            target.password_enc = encrypt_text(password)
            target.account_mask = mask
            target.updated_at = now
            return target

        row = cls(
            user_id=user_id,
            bot_id=bot_id,
            account_enc=encrypt_text(account),
            password_enc=encrypt_text(password),
            account_mask=mask,
            updated_at=now,
        )
        session.add(row)
        # 单用户最多保留 5 组凭证,超出删最旧的
        for old in rows[4:]:
            await session.delete(old)
        return row

    @classmethod
    @with_session
    async def list_credentials(
        cls: type[T_NikiCredential],
        session: AsyncSession,
        *,
        user_id: str,
        bot_id: str,
    ) -> list[T_NikiCredential]:
        """列出该用户保存的全部凭证,按更新时间倒序。"""
        result = await session.execute(
            select(cls)
            .where(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                col(cls.account_enc) != "",
            )
            .order_by(col(cls.updated_at).desc())
        )
        return list(result.scalars().all())

    @classmethod
    @with_session
    async def get_latest_credential(
        cls: type[T_NikiCredential],
        session: AsyncSession,
        *,
        user_id: str,
        bot_id: str,
    ) -> T_NikiCredential | None:
        """取最近保存的一组凭证;无则 None。"""
        result = await session.execute(
            select(cls)
            .where(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                col(cls.account_enc) != "",
            )
            .order_by(col(cls.updated_at).desc())
            .limit(1)
        )
        return result.scalars().first()

    @classmethod
    @with_session
    async def delete_credentials(
        cls: type[T_NikiCredential],
        session: AsyncSession,
        *,
        user_id: str,
        bot_id: str,
    ) -> int:
        """清除该用户保存的全部凭证(退出登录时调用)。"""
        result = await session.execute(
            delete(cls).where(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
            )
        )
        return result.rowcount or 0


@site.register_admin
class NikiCredentialAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(label="无限暖暖保存的凭证", icon="fa fa-key")  # type: ignore
    model = NikiCredential
