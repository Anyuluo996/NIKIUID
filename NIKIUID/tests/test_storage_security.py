"""路径穿越防护测试。"""


import pytest

from gsuid_core.plugins.NIKIUID.NIKIUID.utils.storage_cache import get_user_dir


class TestGetUserDirSecurity:
    """get_user_dir 路径穿越防护"""

    @pytest.fixture
    def base_dir(self, tmp_path):
        return tmp_path / "NIKIUID"

    def test_valid_uid(self, base_dir):
        """合法 uid → 返回子目录"""
        result = get_user_dir(base_dir, "101033914")
        assert result == base_dir / "101033914"

    def test_valid_uid_with_underscore(self, base_dir):
        result = get_user_dir(base_dir, "user_123")
        assert result == base_dir / "user_123"

    def test_path_traversal_dotdot(self, base_dir):
        """../ 注入 → ValueError"""
        with pytest.raises(ValueError):
            get_user_dir(base_dir, "../../../etc")

    def test_path_traversal_single_dotdot(self, base_dir):
        with pytest.raises(ValueError):
            get_user_dir(base_dir, "..")

    def test_empty_uid(self, base_dir):
        """空字符串 → ValueError"""
        with pytest.raises(ValueError):
            get_user_dir(base_dir, "")

    def test_uid_with_slash(self, base_dir):
        """含斜杠 → ValueError"""
        with pytest.raises(ValueError):
            get_user_dir(base_dir, "a/b")

    def test_uid_with_space(self, base_dir):
        """含空格 → ValueError"""
        with pytest.raises(ValueError):
            get_user_dir(base_dir, "a b")

    def test_uid_with_special_chars(self, base_dir):
        """含特殊字符 → ValueError"""
        for bad in ["a;b", "a|b", "$(rm)", "a\nb", "a%00b"]:
            with pytest.raises(ValueError):
                get_user_dir(base_dir, bad)

    def test_create_flag(self, base_dir):
        """create=True 时创建目录"""
        result = get_user_dir(base_dir, "test123", create=True)
        assert result.exists()
        assert result.is_dir()
