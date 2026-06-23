"""NIKIUID 配置管理器实例。"""

from gsuid_core.utils.plugins_config.gs_config import StringConfig

from .config_default import CONFIG_DEFAULT
from ..utils.resource.RESOURCE_PATH import CONFIG_PATH

NikiConfig = StringConfig(
    "NIKIUID",
    CONFIG_PATH,
    CONFIG_DEFAULT,
)
