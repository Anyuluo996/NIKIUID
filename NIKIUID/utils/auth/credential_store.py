"""凭证强加密存储(AES-256-GCM, 认证加密)。

- 密钥: 首次使用时生成 32 字节随机密钥, 落盘 MAIN_PATH/credential.key,
  与数据库分离 —— 单纯拖库(只拿到 DB 文件)无法还原凭证
- 每条凭证独立 12 字节随机 nonce; GCM 自带完整性校验,
  篡改/换密钥解密必然抛错(调用方按"凭证损坏"回退网页登录)
- 可逆: 自动登录需要还原明文, 因此是对称加密而非哈希;
  服务器文件与数据库同时泄露仍可解, 页面勾选处已向用户明示风险
"""

from __future__ import annotations

import os
import base64
from pathlib import Path

from Crypto.Cipher import AES

_KEY_LEN = 32
_NONCE_LEN = 12
_TAG_LEN = 16


def _key_path() -> Path:
    # 局部导入避免模块加载期的潜在循环依赖(credential_store 位于 utils/auth/ 下)
    from ..resource.RESOURCE_PATH import MAIN_PATH

    return MAIN_PATH / "credential.key"


def _load_key() -> bytes:
    path = _key_path()
    if path.is_file():
        try:
            key = base64.urlsafe_b64decode(path.read_bytes().strip())
            if len(key) == _KEY_LEN:
                return key
        except Exception:
            pass
        # 密钥文件无效: 旧密文已不可解(reveal 走"损坏"回退), 直接重建
    key = os.urandom(_KEY_LEN)
    path.write_bytes(base64.urlsafe_b64encode(key))
    return key


def encrypt_text(text: str) -> str:
    """强加密(每条独立随机 nonce)。"""
    nonce = os.urandom(_NONCE_LEN)
    cipher = AES.new(_load_key(), AES.MODE_GCM, nonce=nonce)
    ct, tag = cipher.encrypt_and_digest(text.encode("utf-8"))
    return base64.urlsafe_b64encode(nonce + tag + ct).decode("ascii")


def decrypt_text(blob: str) -> str:
    """解密; 密钥不匹配/密文被篡改/格式损坏时抛 ValueError。"""
    raw = base64.urlsafe_b64decode(blob.encode("ascii"))
    if len(raw) < _NONCE_LEN + _TAG_LEN:
        raise ValueError("credential blob too short")
    nonce = raw[:_NONCE_LEN]
    tag = raw[_NONCE_LEN : _NONCE_LEN + _TAG_LEN]
    ct = raw[_NONCE_LEN + _TAG_LEN :]
    cipher = AES.new(_load_key(), AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ct, tag).decode("utf-8")


def mask_account(account: str) -> str:
    """账号打码展示:138****1234 / ab***cd。"""
    if not account:
        return "***"
    if len(account) <= 4:
        return "*" * len(account)
    if len(account) < 8:
        return f"{account[:2]}***{account[-2:]}"
    return f"{account[:3]}****{account[-4:]}"
