"""加密 + 脱敏测试。"""

from gsuid_core.plugins.NIKIUID.NIKIUID.utils.auth.crypto import (
    _pkcs7_pad,
    _pkcs7_unpad,
    aes_encrypt,
    aes_decrypt,
)
from gsuid_core.plugins.NIKIUID.NIKIUID.utils.auth.passport import (
    _mask_text,
    _mask_phone,
)


class TestPkcs7:
    """PKCS7 填充/去填充"""

    def test_pad_unpad_roundtrip(self):
        data = b"hello world"
        padded = _pkcs7_pad(data)
        assert _pkcs7_unpad(padded) == data

    def test_pad_adds_full_block_on_aligned(self):
        """恰好 16 字节 → 补一整块(16 字节)"""
        data = b"a" * 16
        padded = _pkcs7_pad(data)
        assert len(padded) == 32
        assert padded[-1] == 16

    def test_pad_empty(self):
        padded = _pkcs7_pad(b"")
        assert len(padded) == 16
        assert padded == b"\x10" * 16


class TestAes:
    """AES-CBC 加解密"""

    def test_roundtrip_ascii(self):
        key = "1234567890abcdef"
        plaintext = "hello niki"
        assert aes_decrypt(aes_encrypt(plaintext, key), key) == plaintext

    def test_roundtrip_chinese(self):
        key = "1234567890abcdef"
        plaintext = "无限暖暖搭配师"
        assert aes_decrypt(aes_encrypt(plaintext, key), key) == plaintext

    def test_roundtrip_empty(self):
        key = "1234567890abcdef"
        assert aes_decrypt(aes_encrypt("", key), key) == ""

    def test_roundtrip_long_key_truncated(self):
        """超过 16 字符的 key 被截断到 16"""
        key = "1234567890abcdefghijk"
        plaintext = "test"
        assert aes_decrypt(aes_encrypt(plaintext, key), key) == plaintext

    def test_deterministic_output(self):
        """相同输入 → 相同输出(确定性加密)"""
        key = "1234567890abcdef"
        plaintext = "test"
        c1 = aes_encrypt(plaintext, key)
        c2 = aes_encrypt(plaintext, key)
        assert c1 == c2


class TestMaskText:
    """日志脱敏"""

    def test_normal(self):
        assert _mask_text("abcdefg123456") == "abcd***"

    def test_short_string(self):
        """短于 keep 的字符串 → 全部掩码"""
        assert _mask_text("ab") == "**"

    def test_exact_keep_length(self):
        """等于 keep 长度 → 全部掩码"""
        assert _mask_text("abcd") == "****"

    def test_empty(self):
        assert _mask_text("") == "***"

    def test_custom_keep(self):
        assert _mask_text("abcdef", keep=2) == "ab***"


class TestMaskPhone:
    """手机号脱敏"""

    def test_normal_11_digits(self):
        """11 位手机号 → 前 3 后 4"""
        assert _mask_phone("13812345678") == "138****5678"

    def test_short_number(self):
        """短号 → 兜底到 _mask_text"""
        result = _mask_phone("12345")
        assert "***" in result

    def test_empty(self):
        assert _mask_phone("") == "***"

    def test_seven_digits(self):
        """7 位号 → 可以正常打码"""
        result = _mask_phone("1234567")
        assert "123" in result and "4567" in result
