"""凭证强加密存储测试 — credential_store(AES-256-GCM)。

NikiCredential 的 DB 方法依赖 core 数据库引擎,由 smoke/生产覆盖;
这里验证加密算法本身的往返、随机 nonce 与防篡改语义。
"""

import base64

import pytest

from gsuid_core.plugins.NIKIUID.NIKIUID.utils.auth.credential_store import (
    decrypt_text,
    encrypt_text,
    mask_account,
)


class TestEncryptRoundtrip:
    def test_roundtrip(self):
        blob = encrypt_text("13812345678")
        assert blob != "13812345678"
        assert decrypt_text(blob) == "13812345678"

    def test_roundtrip_unicode_and_long(self):
        secret = "nikki@example.com: P@ssw0rd-密码!#%"
        assert decrypt_text(encrypt_text(secret)) == secret

    def test_same_text_different_blob(self):
        """每条独立随机 nonce, 同明文两次密文不同"""
        assert encrypt_text("same-password") != encrypt_text("same-password")

    def test_tamper_detection(self):
        """GCM 认证加密: 翻转密文任意字节, 解密必然失败"""
        blob = encrypt_text("13812345678")
        raw = bytearray(base64.urlsafe_b64decode(blob))
        raw[-1] ^= 0xFF
        tampered = base64.urlsafe_b64encode(bytes(raw)).decode("ascii")
        with pytest.raises(ValueError):
            decrypt_text(tampered)

    def test_garbled_blob_raises(self):
        with pytest.raises(ValueError):
            decrypt_text("not-a-valid-blob!!")

    def test_key_file_survives_across_calls(self, tmp_path, monkeypatch):
        """密钥文件持久化: 生成后反复解密均可用, 且是 32 字节密钥"""
        from gsuid_core.plugins.NIKIUID.NIKIUID.utils.auth import (
            credential_store,
        )

        key_file = tmp_path / "credential.key"
        monkeypatch.setattr(credential_store, "_key_path", lambda: key_file)

        blob = encrypt_text("secret-账号")
        assert key_file.is_file()
        assert len(base64.urlsafe_b64decode(key_file.read_bytes())) == 32
        # 再次加密/解密(重新读文件)仍可用
        assert decrypt_text(blob) == "secret-账号"
        assert decrypt_text(encrypt_text("second")) == "second"

    def test_invalid_key_file_regenerates(self, tmp_path, monkeypatch):
        """密钥文件损坏时重建(旧密文此后不可解, reveal 走损坏回退)"""
        from gsuid_core.plugins.NIKIUID.NIKIUID.utils.auth import (
            credential_store,
        )

        key_file = tmp_path / "credential.key"
        key_file.write_bytes(b"!!!not-a-key!!!")
        monkeypatch.setattr(credential_store, "_key_path", lambda: key_file)

        blob = encrypt_text("after-regen")
        assert decrypt_text(blob) == "after-regen"


class TestMaskAccount:
    def test_phone(self):
        assert mask_account("13812345678") == "138****5678"

    def test_short_account(self):
        assert mask_account("abcd") == "****"

    def test_medium_account(self):
        assert mask_account("abcdef") == "ab***ef"

    def test_email_like(self):
        assert mask_account("nikki@example.com") == "nik****.com"

    def test_empty(self):
        assert mask_account("") == "***"
