"""用户缓存数据管理"""

import json
import re
from pathlib import Path
from typing import Any

from gsuid_core.logger import logger

# 用户目录名(uid/openid)只允许字母数字下划线短横线,杜绝 ../ 路径穿越
_SAFE_UID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _default_logger():
    return logger


def get_user_dir(plugin_data_dir: Path, uid: str, create: bool = False) -> Path:
    """获取用户数据目录

    Args:
        plugin_data_dir: 插件数据目录
        uid: 用户ID（应该是游戏UID，不是platform_user_id）
        create: 是否创建目录（默认不创建）

    Returns:
        用户数据目录路径

    Raises:
        ValueError: uid 含非法字符(路径穿越防护)
    """
    if not uid or not _SAFE_UID_RE.match(str(uid)):
        raise ValueError(f"非法 uid,拒绝路径构造: {uid!r}")
    user_dir = plugin_data_dir / str(uid)
    # 二次校验:resolve 后必须仍在 plugin_data_dir 之下
    if not user_dir.resolve().is_relative_to(plugin_data_dir.resolve()):
        raise ValueError(f"uid 导致路径越界,拒绝: {uid!r}")
    if create:
        user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


async def load_cached_data(
    plugin_data_dir: Path,
    platform_user_id: str,
    logger=None,
) -> dict | None:
    """加载用户数据（根据 platform_user_id 查找）

    Args:
        plugin_data_dir: 插件数据目录
        platform_user_id: 平台用户ID
        logger: 日志记录器

    Returns:
        用户数据字典，未找到返回 None
    """
    log = logger or _default_logger()

    if not plugin_data_dir.exists():
        return None

    for user_dir in plugin_data_dir.iterdir():
        if not user_dir.is_dir():
            continue
        data_file = user_dir / "data.json"
        if not data_file.exists():
            continue
        try:
            with open(data_file, encoding="utf-8") as f:
                data = json.load(f)
            stored_platform_id = data.get("platform_user_id", "")
            if stored_platform_id == platform_user_id:
                return data
        except Exception as e:
            log.error(f"加载缓存数据失败: {e}")
    return None


async def save_cached_data(
    plugin_data_dir: Path,
    uid: str,
    platform_user_id: str,
    data: dict,
    logger=None,
) -> None:
    """保存用户数据到缓存

    Args:
        plugin_data_dir: 插件数据目录
        uid: 游戏搭配师编号
        platform_user_id: 平台用户ID
        data: 用户数据
        logger: 日志记录器
    """
    log = logger or _default_logger()

    # 验证uid是游戏UID而不是platform_user_id
    if uid == platform_user_id:
        log.error(f"错误：uid ({uid}) 与 platform_user_id ({platform_user_id}) 相同，请检查是否传入了正确的游戏UID！")
        return

    log.info(f"保存用户数据: uid={uid}, platform_user_id={platform_user_id}")

    user_dir = get_user_dir(plugin_data_dir, uid, create=True)
    data_file = user_dir / "data.json"
    tmp_file = user_dir / "data.json.tmp"
    data["platform_user_id"] = platform_user_id

    try:
        # 原子写:先写临时文件,再 os.replace 替换,避免中途崩溃留下损坏 JSON
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        import os

        os.replace(tmp_file, data_file)
        log.info(f"数据已保存到: {data_file}")
    except Exception as e:
        log.error(f"保存缓存数据失败: {e}")
        tmp_file.unlink(missing_ok=True)
