"""奇想手账卡片渲染"""

import datetime
import logging
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .resource.RESOURCE_PATH import TEMPLATE_PATH as HTML_DIR

logger = logging.getLogger("niki.render")


def get_regions() -> list[dict[str, Any]]:
    """返回地区数据配置"""
    return [
        {
            "id": 1,
            "name": "心愿原野",
            "icon": "whimy_star",
            "items": [
                {
                    "id": "whimy_star",
                    "name": "奇想星",
                    "icon": "whimy_star",
                    "key": "star",
                },
                {
                    "id": "inspiration_dew",
                    "name": "灵感露珠",
                    "icon": "inspiration_dew",
                    "key": "dewdrop",
                },
                {"id": "pillar", "name": "流转之柱", "icon": "pillar", "key": "pillar"},
            ],
        },
        {
            "id": 2,
            "name": "花焰群岛",
            "icon": "balloon",
            "items": [
                {
                    "id": "balloon",
                    "name": "奇想气球",
                    "icon": "balloon",
                    "key": "balloon",
                },
                {
                    "id": "flame_crystal",
                    "name": "焰光结晶",
                    "icon": "flame_crystal",
                    "key": "flame_crystal",
                },
            ],
        },
        {
            "id": 3,
            "name": "无忧岛",
            "icon": "bubble",
            "items": [
                {"id": "bubble", "name": "奇想气泡", "icon": "bubble", "key": "bubble"},
                {
                    "id": "carefree_bead",
                    "name": "无忧凝珠",
                    "icon": "carefree_bead",
                    "key": "carefree_bead",
                },
            ],
        },
        {
            "id": 4,
            "name": "丹青屿",
            "icon": "whimy_jade",
            "items": [
                {
                    "id": "whimy_jade",
                    "name": "奇想玉琚",
                    "icon": "whimy_jade",
                    "key": "whimy_jade",
                },
                {
                    "id": "danqing_jade",
                    "name": "丹青玉魄",
                    "icon": "danqing_jade",
                    "key": "danqing_jade",
                },
                {
                    "id": "pillar_danqing",
                    "name": "流转之柱",
                    "icon": "pillar",
                    "key": "pillar_danqing",
                },
            ],
        },
        {
            "id": 5,
            "name": "伊赞之土",
            "icon": "whimy_star_yz",
            "items": [
                {
                    "id": "whimystar_num_yz",
                    "name": "奇想星",
                    "icon": "whimy_star",
                    "key": "whimy_star_yz",
                },
                {
                    "id": "dew_num_yz",
                    "name": "灵感露珠",
                    "icon": "inspiration_dew",
                    "key": "dewdrop_yz",
                },
                {
                    "id": "pillar_yz",
                    "name": "流转之柱",
                    "icon": "pillar",
                    "key": "pillar_yz",
                },
            ],
        },
    ]


def build_journal_context(
    data: dict,
    login_info: dict | None = None,
    map_data: dict | None = None,
    get_user_dir_fn: Any = None,
) -> dict[str, Any]:
    """构建奇想手账模板上下文

    Args:
        data: journal_data 字典
        login_info: 登录信息（可选）
        map_data: 地图数据（可选）
        get_user_dir_fn: 获取用户目录的函数（可选）
    """
    state = data.get("state", {})
    user_data = state.get("userData", {})
    user_self_data = state.get("userSelfData", {})

    user_info = {}
    if login_info:
        user_info = login_info.get("user_info", {})
    role_info = user_info.get("role", {})

    role_id = user_data.get("role_id", role_info.get("uid", ""))

    # 头像路径
    avatar_path_str = ""
    if get_user_dir_fn and role_id:
        avatar_path = get_user_dir_fn(str(role_id)) / "avatar.png"
        if avatar_path.exists():
            avatar_path_str = f"file:///{str(avatar_path).replace(chr(92), '/')}"
    if not avatar_path_str:
        avatar_path_str = role_info.get("avatar", "")

    collected_items = {}
    if map_data:
        collected_items = map_data.get("collectedItems", {})

    # 从 catalog/list 提取各类收集物总量(已收集来自 map_data 列表长度)
    # catalog 结构: {list: [{id, catalogs: [{id, name, count}]}]}
    import json as _json
    catalog = (map_data or {}).get("__catalog", {})
    cat_totals: dict[int, int] = {}  # sub_id -> total count
    for cat in catalog.get("list", []):
        for sub in cat.get("catalogs", []):
            sid = sub.get("id")
            if sid:
                cat_totals[sid] = int(sub.get("count", 0) or 0)

    def _parse_name(val):
        if isinstance(val, list):
            return val[0].get("text", "") if val else ""
        if isinstance(val, str):
            try:
                arr = _json.loads(val.strip('"'))
                return arr[0].get("text", "") if arr else ""
            except Exception:
                return val
        return str(val)

    def _count(lst_val):
        return len(lst_val) if isinstance(lst_val, list) else 0

    # 已收集(map/user/info) / 总量(catalog/list)
    pillar_collected = _count((map_data or {}).get("pillar"))
    star_collected = _count((map_data or {}).get("star"))
    dew_collected = _count((map_data or {}).get("dewdrop"))
    box_collected = _count((map_data or {}).get("box"))
    read_collected = _count((map_data or {}).get("read"))
    cruise_collected = _count((map_data or {}).get("cruise"))

    pillar_total = cat_totals.get(10, 0)      # 流转之柱
    star_total = cat_totals.get(11, 0)        # 奇想星
    dew_total = cat_totals.get(12, 0)         # 灵感露珠
    # 宝箱总量 = 各类宝箱合计
    box_total = sum(cat_totals.get(i, 0) for i in [13, 14, 15, 16, 259])
    read_total = cat_totals.get(20, 0)        # 阅读物
    cruise_total = cat_totals.get(109, 0)     # 世界巡游

    # 游戏时长:API 返回的是秒,转成小时
    raw_play_time = int(user_data.get("total_play_time", 0) or 0)
    play_time_hours = raw_play_time // 3600 if raw_play_time else 0

    # 从 suitCardListData 计算真实共鸣统计(userData 里的 draw_num 等恒为 0)
    suit_list = state.get("suitCardListData", []) or []
    reso_stats = {"limited_5": [0, 0, 0, 0], "limited_4": [0, 0, 0, 0],
                  "permanent_5": [0, 0, 0, 0], "permanent_4": [0, 0, 0, 0]}
    # 每项 = [总套装数, 已共鸣数, 总抽数, 收集件数]
    for s in suit_list:
        level = int(s.get("level", 5) or 5)
        pool = "permanent" if str(s.get("card_pool_id", "")) == "1" else "limited"
        key = f"{pool}_{level}"
        if key in reso_stats:
            reso_stats[key][0] += 1
            total_draw = int(s.get("totalDrawNum", 0) or 0)
            collected = int(s.get("collectedCount", 0) or 0)
            if total_draw > 0 or collected > 0:
                reso_stats[key][1] += 1
            reso_stats[key][2] += total_draw + collected
            reso_stats[key][3] += collected

    def _avg(stat):
        return round(stat[2] / stat[3], 1) if stat[3] > 0 else 0

    # 服装/共鸣套装数:userData 里恒为 0,从 suitCardListData 计算
    owned_suit_count = sum(
        1 for s in suit_list
        if int(s.get("totalDrawNum", 0) or 0) > 0 or int(s.get("collectedCount", 0) or 0) > 0
    )
    total_cloths = sum(int(s.get("collectedCount", 0) or 0) for s in suit_list)

    def _ud(key, default=0):
        """从 userData 取值(info_from_gm 合并后的)"""
        return user_data.get(key, default)

    return {
        "nickname": role_info.get("nickname")
        or user_self_data.get("nickname")
        or "未知",
        "level": user_data.get("level", role_info.get("level", 0)),
        "role_id": role_id,
        "avatar_path": avatar_path_str,
        "login_days": _ud("login_days"),
        "total_play_time": play_time_hours,
        # 基础统计(info_from_gm 真实值)
        "cloth_num": _ud("cloth_num") or total_cloths,
        "momo_num": _ud("momo_num"),
        "designdrawing_num": _ud("designdrawing_num"),
        "achievement_num": _ud("achievement_num"),
        "reading_exploration": _ud("reading_exploration"),
        "creature_explore_num": _ud("creature_explore_num"),
        "energy": _ud("energy"),
        "daily_task": _ud("daily_task"),
        "title_str": _ud("title_str", ""),
        # 心愿原野(info_from_gm 真实值 / 硬编码分母)
        "whimystar_num": _ud("whimsystar_num") or star_collected,
        "dew_num": _ud("dew_num") or dew_collected,
        "pillar_num": _ud("pillar_num") or pillar_collected,
        "permanent_tower": _ud("permanent_tower"),
        "star_sea": _ud("star_sea"),
        # 花焰群岛
        "imagine_ballon_num": _ud("imagine_ballon_num"),
        "flame_light_stone_num": _ud("flame_light_stone_num"),
        # 无忧岛
        "imagine_foam_num": _ud("imagine_foam_num"),
        "worry_free_beads_num": _ud("worry_free_beads_num"),
        # 丹青屿
        "imagine_jade_num": _ud("imagine_jade_num"),
        "danqing_jade_num": _ud("danqing_jade_num"),
        # 伊赞之土/万相境
        "imagine_lantern_num": _ud("imagine_lantern_num"),
        "imagine_bell_num": _ud("imagine_bell_num"),
        # 伊赞奇想星/露珠(currency_count)
        "whimsystar_yz": _ud("currency_25"),
        "dew_yz": _ud("currency_24"),
        # 共鸣统计(info_from_gm 真实值)
        "draw_num": _ud("draw_num"),
        "periodic_draw_num": _ud("periodic_draw_num"),
        "permanent_draw_num": _ud("permanent_draw_num"),
        # 地图探索(已收集 / catalog 总量)
        "box_collected": box_collected,
        "box_total": box_total,
        "read_collected": read_collected,
        "read_total": read_total,
        "cruise_collected": cruise_collected,
        "cruise_total": cruise_total,
        # 共鸣套装统计(从 suitCardListData 计算)
        "limited5_total": reso_stats["limited_5"][0],
        "limited5_owned": reso_stats["limited_5"][1],
        "limited5_draws": reso_stats["limited_5"][2],
        "limited5_avg": _avg(reso_stats["limited_5"]),
        "limited4_total": reso_stats["limited_4"][0],
        "limited4_owned": reso_stats["limited_4"][1],
        "limited4_draws": reso_stats["limited_4"][2],
        "limited4_avg": _avg(reso_stats["limited_4"]),
        "permanent5_total": reso_stats["permanent_5"][0],
        "permanent5_owned": reso_stats["permanent_5"][1],
        "permanent5_draws": reso_stats["permanent_5"][2],
        "permanent5_avg": _avg(reso_stats["permanent_5"]),
        "regions": get_regions(),
        "collected_items": collected_items,
        "user_data": user_data,
        "icon_path": "images/icon",
        "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


async def render_journal_card(
    data: dict,
    login_info: dict | None = None,
    map_data: dict | None = None,
    get_user_dir_fn: Any = None,
    render_fn: Any = None,
) -> str | None:
    """渲染奇想手账卡片

    Args:
        data: journal_data 字典
        login_info: 登录信息
        map_data: 地图数据
        get_user_dir_fn: 获取用户目录的函数
        render_fn: HTML 渲染函数，接收 (html_content) 返回截图路径

    Returns:
        截图文件路径，失败返回 None
    """
    try:
        context = build_journal_context(data, login_info, map_data, get_user_dir_fn)

        env = Environment(loader=FileSystemLoader(str(HTML_DIR)))
        template = env.get_template("niki_journal.html")
        html_content = template.render(**context)

        if render_fn:
            return await render_fn(html_content)

        logger.warning("render_fn not provided, returning None")
        return None

    except Exception as e:
        logger.error(f"渲染奇想手账卡片失败: {e}")
        return None
