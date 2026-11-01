"""NikiCredential 真实落库回归测试。

历史事故: User 基类的 cookie 列 NOT NULL 且无列默认, INSERT 未带
直接 IntegrityError, 而登录侧吞掉异常导致常规 mock 测试全绿。
本文件用临时 sqlite 引擎注入 base_models.async_maker, 走真实 INSERT。
"""

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gsuid_core.utils.database import base_models
from gsuid_core.plugins.NIKIUID.NIKIUID.utils.database import NikiCredential


@pytest.fixture()
def cred_db(tmp_path: Path, monkeypatch) -> None:
    """临时 sqlite 库 + 仅建 niki 表, 替换核心全局会话工厂。"""
    db = tmp_path / "cred.db"
    sync_engine = create_engine(f"sqlite:///{db.as_posix()}")
    NikiCredential.__table__.create(sync_engine, checkfirst=True)
    sync_engine.dispose()

    engine = create_async_engine(f"sqlite+aiosqlite:///{db.as_posix()}")
    monkeypatch.setattr(
        base_models, "async_maker",
        async_sessionmaker(engine, expire_on_commit=False),
    )


class TestCredentialPersistence:
    def test_save_real_insert(self, cred_db):
        """保存凭证必须能真实 INSERT(cookie NOT NULL 曾炸掉落库)。"""
        row = asyncio.run(NikiCredential.save_credential(
            user_id="u1", bot_id="onebot",
            account="user@example.com", password="p@ss",
        ))
        assert row.id is not None
        assert row.cookie == ""  # 基类 NOT NULL 列已显式补空串

        latest = asyncio.run(NikiCredential.get_latest_credential(
            user_id="u1", bot_id="onebot",
        ))
        assert latest is not None
        assert latest.reveal() == ("user@example.com", "p@ss")

    def test_upsert_same_account(self, cred_db):
        """同账号再次保存应 upsert 而非新增行。"""
        for pwd in ("first", "second"):
            asyncio.run(NikiCredential.save_credential(
                user_id="u1", bot_id="onebot",
                account="user@example.com", password=pwd,
            ))
        rows = asyncio.run(NikiCredential.list_credentials(
            user_id="u1", bot_id="onebot",
        ))
        assert len(rows) == 1
        assert rows[0].reveal()[1] == "second"

    def test_cap_five_credentials(self, cred_db):
        """单用户最多保留 5 组凭证。"""
        for i in range(7):
            asyncio.run(NikiCredential.save_credential(
                user_id="u2", bot_id="onebot",
                account=f"acc{i}", password="x",
            ))
        rows = asyncio.run(NikiCredential.list_credentials(
            user_id="u2", bot_id="onebot",
        ))
        assert len(rows) == 5
        assert all("acc0" not in r.account_mask for r in rows)
        assert all("acc1" not in r.account_mask for r in rows)

    def test_delete_credentials(self, cred_db):
        asyncio.run(NikiCredential.save_credential(
            user_id="u3", bot_id="onebot", account="a", password="b",
        ))
        n = asyncio.run(NikiCredential.delete_credentials(
            user_id="u3", bot_id="onebot",
        ))
        assert n == 1
        assert asyncio.run(NikiCredential.get_latest_credential(
            user_id="u3", bot_id="onebot",
        )) is None
