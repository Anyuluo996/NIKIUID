"""奇想手账数据获取服务"""

from __future__ import annotations

from typing import Any

import aiohttp

from gsuid_core.logger import logger

from ..auth.passport import myl_sign_params
from ..constants import CLIENT_ID, MYL_API_BASE
from .resonance_service import fetch_resonance_with_api


async def fetch_journal_data(
    token: str,
    openid: str,
    client_id: int | None = None,
) -> dict | None:
    """使用 token 获取完整奇想手账数据

    Args:
        token: 登录 token
        openid: 用户 openid
        client_id: 客户端ID（默认 CLIENT_ID）

    Returns:
        包含 journal_data、login_info、map_data、resonance_data 的字典，失败返回 None
    """
    cid = client_id or CLIENT_ID

    if not token or not openid:
        logger.error("token 或 openid 为空")
        return None

    user_info: dict[str, Any] = {}
    map_data: dict[str, Any] = {}
    resonance_data: dict[str, Any] = {}

    try:
        base_params = {
            "client_id": cid,
            "token": token,
            "openid": openid,
        }

        async with aiohttp.ClientSession() as session:
            # 1. 获取用户信息
            try:
                api_url = f"{MYL_API_BASE}/v1/strategy/user/info/get"
                api_data = myl_sign_params(base_params.copy())
                async with session.post(
                    api_url, json=api_data, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        logger.debug(f"[niki] 用户信息 API 响应: {result}")
                        if result.get("code") == 0 and result.get("data"):
                            user_info = result.get("data")
                        else:
                            error_code = result.get("code", -1)
                            error_info = result.get("info", "Unknown error")
                            logger.error(
                                f"用户信息API返回错误: code={error_code}, info={error_info}"
                            )
                    else:
                        logger.error(f"用户信息API返回非200状态: {resp.status}")
            except Exception as e:
                logger.warning(f"获取用户信息API失败: {e}")

            # 2. 获取共鸣数据
            try:
                resonance_data = (
                    await fetch_resonance_with_api(token, openid, cid) or {}
                )
            except Exception as e:
                logger.warning(f"获取共鸣数据失败: {e}")

            # 3. 获取地图数据
            try:
                map_api_url = f"{MYL_API_BASE}/v1/strategy/map/user/info"
                map_api_data = myl_sign_params(base_params.copy())
                async with session.post(
                    map_api_url,
                    json=map_api_data,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        map_result = await resp.json()
                        logger.debug(f"[niki] 地图 API 响应: {map_result}")
                        if map_result.get("code") == 0:
                            map_data = map_result.get("data", {})
            except Exception as e:
                logger.warning(f"获取地图API失败: {e}")

            # 4. 获取地图目录(各类收集物总量)
            try:
                catalog_api_url = f"{MYL_API_BASE}/v1/strategy/map/catalog/list"
                catalog_api_data = myl_sign_params(base_params.copy())
                async with session.post(
                    catalog_api_url,
                    json=catalog_api_data,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        catalog_result = await resp.json()
                        if catalog_result.get("code") == 0:
                            map_data["__catalog"] = catalog_result.get("data", {})
            except Exception as e:
                logger.warning(f"获取地图目录API失败: {e}")

        # 构建 journal_data 结构
        state = {
            "userData": {},
            "userSelfData": {},
        }

        # 验证用户信息是否有效
        if not user_info or not isinstance(user_info, dict):
            logger.error("用户信息为空或格式错误，无法继续处理")
            return None

        role = user_info.get("role", {})
        if not role:
            logger.error("用户信息中缺少role字段")
            return None

        state["userData"]["role_id"] = role.get("uid")
        state["userData"]["nickname"] = role.get("nickname", "未知")
        state["userData"]["level"] = role.get("level", 0)
        state["userData"]["avatar"] = role.get("avatar", "")

        # 从 note/book/info 的 info_from_gm 提取完整用户统计(45 字段)
        # info_from_gm 的 whimsystar_num/dew_num/pillar_num 等已经是心愿原野的真实值
        # (文档 DATA_FIELDS.md 第 2.5 节验证: dew_num=1926 是心愿原野, 不是全局 4020)
        # currency_count[item_id=7/8] 是心愿原野的露珠/星,[24/25] 是伊赞之土的
        resonance_stats = resonance_data.get("userSelfStats", {})
        for key, value in resonance_stats.items():
            state["userData"][key] = value

        # 注意:不再用 map_data 列表长度覆盖 userData 的探索字段
        # map_data 的 pillar/star/dewdrop 是全局所有区域的合计(含多版本累计),
        # 而 userData 的值是心愿原野专属的, 覆盖会导致数据错误(如露珠 1926→4020)。
        # map_data 仅用于"其它收集"区域的 box/read/cruise 统计(在 render 层单独处理)。

        if resonance_data:
            state["reasonaceCardData"] = resonance_data
            state["suitCardListData"] = resonance_data.get(
                "suitCardListData", resonance_data.get("list", [])
            )

        journal_data = {"state": state}

        login_info = {
            "user_info": user_info,
            "token": token,
            "openid": openid,
        }

        return {
            "login_info": login_info,
            "journal_data": journal_data,
            "map_data": map_data,
            "resonance_data": resonance_data,
        }

    except Exception as e:
        logger.error(f"使用 token 获取数据失败: {e}")
        return None
