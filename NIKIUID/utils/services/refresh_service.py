"""数据刷新服务

登录成功或用户主动刷新时调用。完整流程:
1. 保存 token 到 NikiUser 表
2. 获取奇想手账数据
3. 保存 JSON 缓存到用户数据目录
4. 下载头像和套装图片
"""

from __future__ import annotations

from pathlib import Path

import aiohttp

from gsuid_core.logger import logger

from ..database import NikiUser
from ..encoding import fix_encoding
from ..resource.RESOURCE_PATH import USER_DATA_PATH
from ..storage_assets import download_suit_images
from ..storage_cache import save_cached_data
from .journal_service import fetch_journal_data

# 套装图片统一存放在用户数据目录下的 suits 子目录
IMAGES_DIR = USER_DATA_PATH / "suits"


async def refresh_user_data(
    *,
    user_id: str,
    bot_id: str,
    token_info: dict,
    auto_refresh: bool = True,
) -> dict | None:
    """刷新用户数据

    Args:
        user_id: 聊天平台用户ID
        bot_id: 机器人ID
        token_info: 登录凭证(token、openid、client_id 等)
        auto_refresh: 是否自动获取数据;False 则只保存凭证

    Returns:
        包含 uid / nickname / level / success 等信息的字典
    """
    openid = str(token_info.get("openid", ""))
    token = str(token_info.get("token", ""))
    client_id = int(token_info.get("client_id", 1106) or 1106)
    area_id = int(token_info.get("area_id", 1) or 1)
    device_id = str(token_info.get("device_id", ""))

    if not openid or not token:
        logger.error("[refresh] token_info 缺少 openid 或 token")
        return {"success": False, "refresh_status": "登录凭证不完整"}

    logger.debug(f"[refresh] user_id={user_id} openid={openid[:8]}***")

    # 1. 保存 token 到数据库
    await NikiUser.save_token(
        user_id=user_id,
        bot_id=bot_id,
        openid=openid,
        token=token,
        device_id=device_id,
        client_id=client_id,
        area_id=area_id,
    )

    result: dict = {
        "uid": "",
        "refresh_status": "",
        "success": False,
    }

    if not auto_refresh:
        result["success"] = True
        result["refresh_status"] = "仅保存凭证"
        return result

    # 2. 获取数据
    data_result = await fetch_journal_data(
        token=token,
        openid=openid,
        client_id=client_id,
    )

    if not data_result:
        result["refresh_status"] = "数据刷新失败：token可能已过期或API返回空数据"
        return result

    # 3. 验证数据完整性
    journal_data = data_result.get("journal_data", {})
    login_info = data_result.get("login_info", {})
    user_info = login_info.get("user_info", {})
    role_info = user_info.get("role", {})
    state = journal_data.get("state", {})

    nickname = role_info.get("nickname") or state.get("userData", {}).get("nickname")
    # level 用 is None 判断,允许合法的 0 级
    role_level = role_info.get("level")
    level = role_level if role_level is not None else state.get("userData", {}).get("level")

    if not nickname or level is None:
        error_msg = []
        if not nickname:
            error_msg.append("无法获取用户昵称")
        if level is None:
            error_msg.append("无法获取用户等级")
        logger.error(f"数据刷新失败：{'; '.join(error_msg)}")
        result["refresh_status"] = (
            f"数据刷新失败：{'; '.join(error_msg)}，请检查token是否有效或重新登录"
        )
        return result

    uid = str(role_info.get("uid", state.get("userData", {}).get("role_id", openid)))

    # 保存 JSON 缓存(用 uid 作为目录名,openid 作为内部 platform_user_id)
    await save_cached_data(USER_DATA_PATH, uid, openid, data_result, logger)

    # 回写展示字段到数据库
    await NikiUser.update_profile(
        user_id=user_id,
        bot_id=bot_id,
        openid=openid,
        uid=uid,
        nickname=nickname,
        level=int(level) if level is not None else 0,
    )

    # 4. 下载头像
    try:
        avatar_url = role_info.get("avatar", "")
        if avatar_url and uid:
            user_dir = USER_DATA_PATH / uid
            user_dir.mkdir(parents=True, exist_ok=True)
            avatar_path = user_dir / "avatar.png"
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    avatar_url, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status == 200:
                        avatar_path.write_bytes(await resp.read())
                        logger.info(f"头像已保存: {avatar_path}")
    except Exception as e:
        logger.warning(f"下载头像失败: {e}")

    # 5. 下载套装图片(统一存到 USER_DATA_PATH/suits)
    try:
        suit_card_list = state.get("suitCardListData", [])
        if suit_card_list:
            IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            await download_suit_images(
                suit_card_list,
                IMAGES_DIR,
                fix_fn=fix_encoding,
                logger=logger,
            )
    except Exception as e:
        logger.warning(f"下载套装图片失败: {e}")

    result["uid"] = uid
    result["success"] = True
    result["refresh_status"] = "数据已刷新"
    result["nickname"] = nickname or "未知"
    result["level"] = int(level or 0)
    return result
