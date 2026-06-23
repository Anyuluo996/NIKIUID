"""获取 NIKIUID 当前生效的前缀。"""

from gsuid_core.sv import get_plugin_available_prefix


def niki_prefix() -> str:
    """返回用户配置或 force_prefix 里的第一个前缀,例如 'niki'。"""
    return get_plugin_available_prefix("NIKIUID")
