"""编码修复工具"""

__all__ = ["fix_encoding"]


def fix_encoding(text: str) -> str:
    """修复编码问题：将 Latin1 编码的 UTF-8 字符串还原为正确的中文

    Args:
        text: 可能存在编码问题的字符串

    Returns:
        修复后的字符串
    """
    if not text:
        return text
    try:
        return text.encode("latin1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError, AttributeError):
        return text
