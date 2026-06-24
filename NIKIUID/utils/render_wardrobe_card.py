"""共鸣衣橱卡片渲染"""

import json
from datetime import datetime
from typing import Any

from gsuid_core.logger import logger

from .encoding import fix_encoding
from .models import PoolType, WardrobeFilterMode
from .resource.RESOURCE_PATH import NIKI_TEMPLATES, USER_DATA_PATH


def _get_level(suit: dict[str, Any]) -> int:
    """从原始数据中获取星级"""
    # 直接使用 API 返回的 level 字段
    return suit.get("level", 5)


def _get_name(suit: dict[str, Any]) -> str:
    """从原始数据中获取套装名"""
    name_list = suit.get("name", [])
    if name_list and isinstance(name_list[0], dict):
        return fix_encoding(name_list[0].get("text", ""))
    return ""


def _get_pool_name(suit: dict[str, Any]) -> str:
    """从原始数据中获取卡池名"""
    pool_list = suit.get("card_pool_name", [])
    if pool_list and isinstance(pool_list[0], dict):
        return fix_encoding(pool_list[0].get("text", ""))
    return ""


def _get_img_url(suit: dict[str, Any]) -> str:
    """从原始数据中获取图片URL"""
    return suit.get("preview_image", "") or suit.get("image", "")


def _get_timestamp(suit: dict[str, Any]) -> int:
    """从原始数据中获取时间戳"""
    ts = suit.get("card_start_timestamp", 0)
    if ts:
        return ts
    # 尝试从时间字符串解析
    time_str = suit.get("card_start_time", "")
    if time_str:
        try:
            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            return int(dt.timestamp())
        except Exception:
            pass
    return 0


def _matches_pool_type(suit: dict[str, Any], pool_type: PoolType | str) -> bool:
    """根据请求的卡池类型筛选套装"""
    expected_level = 5 if str(pool_type).endswith("_5") else 4
    return _get_level(suit) == expected_level


def build_wardrobe_context(
    data: dict,
    pool_type: PoolType | str = "limited_5",
    login_info: dict | None = None,
    get_user_dir_fn: Any = None,
    filter_mode: WardrobeFilterMode = "owned",
) -> dict[str, Any]:
    """构建共鸣衣橱模板上下文

    Args:
        data: journal_data 字典
        pool_type: 卡池类型 ("limited_5" | "limited_4" | "permanent_5" | "permanent_4")
        login_info: 登录信息
        get_user_dir_fn: 获取用户目录的函数
    """
    logger.debug(
        "build_wardrobe_context pool_type=%s filter_mode=%s",
        pool_type,
        filter_mode,
    )

    state = data.get("state", {})
    resonance_data = state.get("reasonaceCardData", {})

    # 直接从原始数据筛选
    raw_suits = state.get("suitCardListData", [])
    owned_suit_ids = resonance_data.get("ownedSuitIds", [])

    # 获取已拥有的套装ID集合
    owned_set = {str(sid) for sid in owned_suit_ids}

    logger.debug("原始数据 count=%s", len(raw_suits))

    # 按星级筛选
    filtered_suits = [s for s in raw_suits if _matches_pool_type(s, pool_type)]
    logger.debug("按星级筛选后 count=%s", len(filtered_suits))

    # 按拥有状态筛选
    if filter_mode == "owned":
        filtered_suits = [s for s in filtered_suits if str(s.get("suit_id", "")) in owned_set]
    elif filter_mode == "not_owned":
        filtered_suits = [s for s in filtered_suits if str(s.get("suit_id", "")) not in owned_set]

    # 转换数据格式（渲染时转换，不保存转换后的数据）
    clothes_data = []
    for suit in filtered_suits:
        suit_id = str(suit.get("suit_id", ""))
        is_owned = suit_id in owned_set
        clothes_data.append({
            "subSuit": _get_name(suit),
            "bigSuit": _get_pool_name(suit),
            "level": _get_level(suit),
            "poolType": "limited",
            # 共鸣抽数数据（从 API 返回的 suit 数据中读取）
            # averageDrawNum 需要保留小数，actualDrawCount 统一在后端计算，避免模板重复拼装。
            "avgDrawNum": float(suit.get("averageDrawNum", 0) or 0),
            "totalDrawNum": int(suit.get("totalDrawNum", 0) or 0),
            "collectedCount": int(suit.get("collectedCount", 0) or 0),
            "actualDrawCount": int(suit.get("totalDrawNum", 0) or 0) + int(suit.get("collectedCount", 0) or 0),
            "isCollected": is_owned,
            "imgUrl": _get_img_url(suit),
            "timestamp": _get_timestamp(suit),
        })

    # 按时间戳排序（从新到旧）
    clothes_data.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    # 替换套装图片为本地路径(优先 file:// 绝对路径,htmlkit 才能读取;
    # 远程 URL 作为兜底,htmlkit 也能加载网络图片)
    suits_dir = USER_DATA_PATH / "suits"
    for suit in clothes_data:
        url = suit.get("imgUrl") or ""
        if not url:
            continue
        filename = url.split("/")[-1]
        if not filename.endswith(".png"):
            filename += ".png"
        local_path = suits_dir / filename
        if local_path.exists():
            # 转 file:// 绝对路径(Windows 路径反斜杠转正斜杠)
            suit["imgUrl"] = f"file:///{str(local_path.resolve()).replace(chr(92), '/')}"

    # 获取用户信息
    user_data = state.get("userData", {})
    user_info = {}
    if login_info:
        user_info = login_info.get("user_info", {})
    role_info = user_info.get("role", {})
    role_id = role_info.get("uid") or user_data.get("role_id", "")

    # 头像路径
    avatar_path_str = ""
    if get_user_dir_fn and role_id:
        avatar_path = get_user_dir_fn(str(role_id)) / "avatar.png"
        if avatar_path.exists():
            avatar_path_str = f"file:///{str(avatar_path.resolve()).replace(chr(92), '/')}"
    if not avatar_path_str:
        avatar_url = role_info.get("avatar", "")
        if avatar_url:
            avatar_path_str = avatar_url

    # 卡池标签
    pool_labels = {
        "limited_5": "五星套装",
        "limited_4": "四星套装",
        "permanent_5": "常驻五星套装",
        "permanent_4": "常驻四星套装",
    }
    pool_label = pool_labels.get(str(pool_type), "五星套装")

    # 统计信息(基于本次筛选后的 clothes_data,与卡片展示一致)
    owned_count = sum(1 for c in clothes_data if c.get("isCollected"))
    suit_count = len(clothes_data)
    total_draws = sum(int(c.get("actualDrawCount", 0) or 0) for c in clothes_data)
    total_collected = sum(int(c.get("collectedCount", 0) or 0) for c in clothes_data)
    avg_draw = round(total_draws / total_collected, 1) if total_collected > 0 else 0
    num_items = len(clothes_data)

    return {
        "nickname": role_info.get("nickname") or "未知",
        "role_id": role_id,
        "level": role_info.get("level") or user_data.get("level", 0),
        "avatar_path": avatar_path_str,
        "pool_type": pool_type,
        "pool_label": pool_label,
        "filter_mode": filter_mode,
        "total": resonance_data.get("total", 0),
        "total_owned": len(owned_set),
        "suits_completed": owned_count,
        "suits_total": len(filtered_suits),
        # 新字段:服务端渲染直接用
        "owned_count": owned_count,
        "suit_count": suit_count,
        "total_draws": total_draws,
        "avg_draw": avg_draw,
        "clothes": clothes_data[:60],
        # 旧字段保留兼容(如有其它地方引用)
        "clothes_json": json.dumps(clothes_data[:60], ensure_ascii=False),
        "icon_path": "images/icon",
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "num_items": num_items,
    }


async def render_wardrobe_card(
    data: dict,
    pool_type: PoolType | str = "limited_5",
    login_info: dict | None = None,
    get_user_dir_fn: Any = None,
    render_fn: Any = None,
    filter_mode: WardrobeFilterMode = "owned",
) -> str | None:
    """渲染共鸣衣橱卡片

    Args:
        data: journal_data 字典
        pool_type: 卡池类型
        login_info: 登录信息
        get_user_dir_fn: 获取用户目录的函数
        render_fn: HTML 渲染函数，接收 (html_content, pool_type) 返回截图路径

    Returns:
        截图文件路径，失败返回 None
    """
    try:
        context = build_wardrobe_context(
            data,
            pool_type,
            login_info,
            get_user_dir_fn,
            filter_mode,
        )

        template = NIKI_TEMPLATES.get_template("wardrobe.html")
        html_content = template.render(**context)

        if render_fn:
            return await render_fn(html_content, pool_type, context.get("num_items", 0))

        logger.warning("render_fn not provided, returning None")
        return None

    except Exception as e:
        logger.error(f"渲染共鸣衣橱卡片失败: {e}")
        return None
