"""共鸣衣橱卡片渲染(单件明细 + 进化次数版)

上下文在前端复刻算法(见 services/draw_num_service.py)产出的
clothDetails / evolutionCount 基础上构建, 模板层只管展示。
"""

import json
from typing import Any
from datetime import datetime

from gsuid_core.logger import logger

from .models import PoolType, WardrobeFilterMode
from .encoding import fix_encoding
from .resource.RESOURCE_PATH import NIKI_TEMPLATES, USER_DATA_PATH
from .services.blessing_service import download_blessing_icons  # 通用下载器

# 单件图标与套装预览图缓存目录
SUITS_DIR = USER_DATA_PATH / "suits"
CLOTHS_DIR = USER_DATA_PATH / "cloths"

# 每页套装数(单件网格较占高度, 分页渲染)
PAGE_SIZE = 8


def _get_level(suit: dict[str, Any]) -> int:
    """从原始数据中获取星级"""
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


def _to_local_file_url(path: Any) -> str:
    try:
        return f"file:///{str(path.resolve()).replace(chr(92), '/')}"
    except Exception:
        return ""


async def localize_images(clothes: list[dict]) -> None:
    """把套装预览图与单件图标替换为本地路径(下载缓存, 缺失时保留远程 URL)。"""
    cloth_urls: list[str] = []
    for suit in clothes:
        for cloth in suit.get("cloths", []) or []:
            url = cloth.get("image") or ""
            if url:
                cloth_urls.append(url)
    if cloth_urls:
        await download_blessing_icons(cloth_urls, CLOTHS_DIR)

    suit_urls = [s.get("imgUrl") for s in clothes if s.get("imgUrl")]
    if suit_urls:
        await download_blessing_icons(suit_urls, SUITS_DIR)

    def _local(url: str, folder: Any) -> str:
        if not url:
            return url
        filename = url.split("/")[-1]
        if not filename.endswith(".png"):
            filename += ".png"
        local_path = folder / filename
        if local_path.exists():
            return _to_local_file_url(local_path)
        return url

    for suit in clothes:
        suit["imgUrl"] = _local(suit.get("imgUrl") or "", SUITS_DIR)
        for cloth in suit.get("cloths", []) or []:
            cloth["image"] = _local(cloth.get("image") or "", CLOTHS_DIR)


def build_wardrobe_context(
    data: dict,
    pool_type: PoolType | str = "limited_5",
    login_info: dict | None = None,
    get_user_dir_fn: Any = None,
    filter_mode: WardrobeFilterMode = "owned",
    page: int = 1,
    page_size: int | None = None,
) -> dict[str, Any] | None:
    """构建共鸣衣橱模板上下文

    Args:
        data: journal_data 字典
        pool_type: 卡池类型 ("limited_5" | "limited_4" | "permanent_5" | "permanent_4")
        login_info: 登录信息
        get_user_dir_fn: 获取用户目录的函数
        filter_mode: "owned" 只看已共鸣 / "all" 全部
        page: 页码(1 起, 每页 page_size 套, 默认 PAGE_SIZE)
        page_size: 每页套装数(杂志风紧凑模板用 16, 横幅详情模板用 8)

    Returns:
        模板上下文; 无匹配套装时返回 None
    """
    logger.debug(
        "build_wardrobe_context pool_type=%s filter_mode=%s page=%s",
        pool_type,
        filter_mode,
        page,
    )

    state = data.get("state", {})
    resonance_data = state.get("reasonaceCardData", {})

    raw_suits = state.get("suitCardListData", [])
    owned_suit_ids = resonance_data.get("ownedSuitIds", [])
    owned_set = {str(sid) for sid in owned_suit_ids}

    # 按星级筛选
    filtered_suits = [s for s in raw_suits if _matches_pool_type(s, pool_type)]

    # 按拥有状态筛选
    if filter_mode == "owned":
        filtered_suits = [
            s for s in filtered_suits if str(s.get("suit_id", "")) in owned_set
        ]
    elif filter_mode == "drawn":
        # 抽到过的套装(含未抽齐): 有共鸣抽数 或 在已共鸣名单里。
        # ownedSuitIds 只含齐套套装, 抽了 5/10 件的套装不在其中, 不能只看名单
        filtered_suits = [
            s
            for s in filtered_suits
            if str(s.get("suit_id", "")) in owned_set
            or int(s.get("totalDrawNum", 0) or 0) > 0
        ]

    if not filtered_suits:
        return None

    # 转换数据格式(渲染时转换, 不保存转换后的数据)
    all_clothes = []
    for suit in filtered_suits:
        suit_id = str(suit.get("suit_id", ""))
        is_owned = suit_id in owned_set

        # 单件明细(共鸣抽数计算服务合并进来的 clothDetails)
        cloths_view = []
        for cloth in suit.get("clothDetails", []) or []:
            cloths_view.append({
                "clothId": str(cloth.get("clothId", "")),
                "name": fix_encoding(str(cloth.get("name", "") or "")),
                "displayType": str(cloth.get("displayType", "") or ""),
                "image": str(cloth.get("image", "") or ""),
                "drawNumFirst": int(cloth.get("drawNumFirst", 0) or 0),
                "drawNumSecond": int(cloth.get("drawNumSecond", 0) or 0),
                "owned": int(cloth.get("drawNumFirst", 0) or 0) > 0,
            })

        # 旧缓存无 clothDetails 时, 从 cloths JSON 字符串补齐(抽数为 0)
        if not cloths_view:
            try:
                raw_cloths = suit.get("cloths", "[]")
                parsed = json.loads(raw_cloths) if isinstance(raw_cloths, str) else raw_cloths
                for cloth in parsed or []:
                    cloths_view.append({
                        "clothId": str(cloth.get("cloth_id", "")),
                        "name": fix_encoding(str(cloth.get("name", "") or "")),
                        "displayType": str(cloth.get("display_type", "") or ""),
                        "image": str(cloth.get("image", "") or ""),
                        "drawNumFirst": 0,
                        "drawNumSecond": 0,
                        "owned": False,
                    })
            except Exception:
                pass

        all_clothes.append({
            "subSuit": _get_name(suit),
            "bigSuit": _get_pool_name(suit),
            "level": _get_level(suit),
            "cardType": int(suit.get("card_type", 2) or 2),
            "poolType": "limited",
            # 共鸣抽数数据(前端复刻算法)
            "avgDrawNum": float(suit.get("averageDrawNum", 0) or 0),
            "totalDrawNum": int(suit.get("totalDrawNum", 0) or 0),
            "collectedCount": int(suit.get("collectedCount", 0) or 0),
            # 去重后的单件拥有数(collectedCount 是槽位数, 含重抽)
            "ownedClothCount": sum(1 for c in cloths_view if c["owned"]),
            "actualDrawCount": int(suit.get("totalDrawNum", 0) or 0)
            + int(suit.get("collectedCount", 0) or 0),
            "evolutionCount": int(suit.get("evolutionCount", 0) or 0),
            "evolutionTotal": int(suit.get("evolutionTotal", 0) or 0),
            "isCollected": is_owned,
            "imgUrl": _get_img_url(suit),
            "timestamp": _get_timestamp(suit),
            "cloths": cloths_view,
        })

    # 按时间戳排序(从新到旧)
    all_clothes.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    total_suits = len(all_clothes)
    effective_page_size = page_size if page_size and page_size > 0 else PAGE_SIZE
    total_pages = max(1, (total_suits + effective_page_size - 1) // effective_page_size)
    page = max(1, min(page, total_pages))
    clothes = all_clothes[
        (page - 1) * effective_page_size: page * effective_page_size
    ]

    # 用户信息
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
            avatar_path_str = _to_local_file_url(avatar_path)
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
    pool_subtitles = {
        "limited_5": "五星限定典藏名录",
        "limited_4": "四星限定典藏名录",
        "permanent_5": "常驻五星典藏名录",
        "permanent_4": "常驻四星典藏名录",
    }
    pool_subtitle = pool_subtitles.get(str(pool_type), "五星限定典藏名录")

    # 统计信息(基于全部筛选结果, 不分页)
    owned_count = sum(1 for c in all_clothes if c.get("isCollected"))
    total_draws = sum(int(c.get("actualDrawCount", 0) or 0) for c in all_clothes)
    total_collected = sum(int(c.get("collectedCount", 0) or 0) for c in all_clothes)
    avg_draw = round(total_draws / total_collected, 1) if total_collected > 0 else 0
    total_evolutions = sum(
        int(c.get("evolutionCount", 0) or 0) for c in all_clothes
    )
    max_evolutions = sum(
        int(c.get("evolutionTotal", 0) or 0) for c in all_clothes
    )

    return {
        "nickname": role_info.get("nickname") or "未知",
        "role_id": role_id,
        "level": role_info.get("level") or user_data.get("level", 0),
        "avatar_path": avatar_path_str,
        "pool_type": pool_type,
        "pool_label": pool_label,
        "pool_subtitle": pool_subtitle,
        # 本期焦点: 当前页最新的套装(与典藏长廊第一张呼应, 图片随本页本地化)
        "spotlight": clothes[0] if clothes else None,
        "filter_mode": filter_mode,
        "page": page,
        "total_pages": total_pages,
        "owned_count": owned_count,
        "suit_count": total_suits,
        "total_draws": total_draws,
        "avg_draw": avg_draw,
        "total_collected": total_collected,
        "total_evolutions": total_evolutions,
        "max_evolutions": max_evolutions,
        "clothes": clothes,
        "clothes_json": json.dumps(clothes, ensure_ascii=False),
        "icon_path": "images/icon",
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


async def render_wardrobe_card(
    data: dict,
    pool_type: PoolType | str = "limited_5",
    login_info: dict | None = None,
    get_user_dir_fn: Any = None,
    render_fn: Any = None,
    filter_mode: WardrobeFilterMode = "owned",
    template_name: str = "wardrobe.html",
    page: int = 1,
    page_size: int | None = None,
) -> str | None:
    """渲染共鸣衣橱卡片

    Args:
        data: journal_data 字典
        pool_type: 卡池类型
        login_info: 登录信息
        get_user_dir_fn: 获取用户目录的函数
        render_fn: HTML 渲染函数，接收 (html_content, pool_type, num) 返回截图
        filter_mode: owned / all
        template_name: 模板文件名(默认旧版 wardrobe.html, 供 A/B 测试新模板)
        page: 页码
        page_size: 每页套装数(默认 PAGE_SIZE)

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
            page=page,
            page_size=page_size,
        )
        if context is None:
            return None

        if template_name != "wardrobe.html":
            # 新模板: 单件图标本地化
            await localize_images(context["clothes"])

        template = NIKI_TEMPLATES.get_template(template_name)
        html_content = template.render(**context)

        if render_fn:
            return await render_fn(
                html_content, pool_type, context.get("suit_count", 0)
            )

        logger.warning("render_fn not provided, returning None")
        return None

    except Exception as e:
        logger.exception(f"渲染共鸣衣橱卡片失败: {e}")
        return None
