"""NIKIUID 资源路径常量

约定俗成地在 data/ 下建一个以插件名命名的子目录,
参考 NTEUID 的 utils/resource/RESOURCE_PATH.py。
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from gsuid_core.data_store import get_res_path

MAIN_PATH = get_res_path() / "NIKIUID"

CONFIG_PATH = MAIN_PATH / "config.json"

# 用户数据目录(每个游戏 UID 一个子目录,存放 data.json 和下载的套装图片)
USER_DATA_PATH = MAIN_PATH / "user_data"

# 静态只读资源(随插件仓库分发的 HTML 模板)
# RESOURCE_PATH.py 在 NIKIUID/NIKIUID/utils/resource/,模板在内层包 NIKIUID/NIKIUID/templates/
#   parents[0]=resource  parents[1]=utils  parents[2]=NIKIUID(内层)  parents[3]=NIKIUID(外层)
STATIC_RESOURCE_PATH = Path(__file__).parents[2] / "templates"
TEMPLATE_PATH = STATIC_RESOURCE_PATH


def init_dir() -> None:
    """启动时确保所有数据目录存在。"""
    for path in [MAIN_PATH, USER_DATA_PATH]:
        path.mkdir(parents=True, exist_ok=True)


init_dir()

# Jinja2 模板环境,用于渲染登录页 HTML
NIKI_TEMPLATES = Environment(
    loader=FileSystemLoader([str(TEMPLATE_PATH)]),
    enable_async=False,
)
