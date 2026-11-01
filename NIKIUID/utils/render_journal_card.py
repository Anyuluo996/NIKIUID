"""奇想手账卡片渲染"""

import json
from typing import Any
from datetime import datetime

from gsuid_core.logger import logger

from .resource.RESOURCE_PATH import NIKI_TEMPLATES

# exploreResMax 缺失时的分母兜底(2026-11-01 版本值, 会随版本过期)
_RES_MAX_FALLBACK = {
    "whimsystar_max": 378,
    "dew_max": 1993,
    "pillar_max": 240,
    "imagine_ballon_max": 56,
    "flame_light_stone_max": 261,
    "imagine_foam_max": 41,
    "worry_free_beads_max": 233,
    "yzzt_whimsystar_max": 626,
    "yzzt_dew_max": 3203,
}


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

    数值口径(2026-11-01 与线上页面 15/15 对照验证):
    - 心愿原野奇想星/露珠分子: currency_count[item_id=8/7] 优先, igm 字段兜底
    - 大地图流转之柱分子: info_from_gm.pillar_num(全局整数)
    - 万相境/丹青屿分子分母: resourceMap 刷点聚合(exploreOverview)
    - 分母: exploreResMax.json(KV 静态文件), 前端显示分母 = max(分子, 配置分母)

    Args:
        data: journal_data 字典
        login_info: 登录信息（可选）
        map_data: 地图数据（可选）
        get_user_dir_fn: 获取用户目录的函数（可选）
    """
    state = data.get("state", {})
    user_data = state.get("userData", {})
    user_self_data = state.get("userSelfData", {})
    explore = state.get("exploreOverview", {}) or {}
    res_max = {**_RES_MAX_FALLBACK, **(explore.get("resMax") or {})}
    resource_map = explore.get("resourceMap") or {}

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
                arr = json.loads(val.strip('"'))
                return arr[0].get("text", "") if arr else ""
            except Exception:
                return val
        return str(val)

    def _count(lst_val):
        return len(lst_val) if isinstance(lst_val, list) else 0

    # 已收集(map/user/info) / 总量(catalog/list)
    star_collected = _count((map_data or {}).get("star"))
    dew_collected = _count((map_data or {}).get("dewdrop"))
    box_collected = _count((map_data or {}).get("box"))
    read_collected = _count((map_data or {}).get("read"))
    cruise_collected = _count((map_data or {}).get("cruise"))

    # 宝箱总量 = 各类宝箱合计
    box_total = sum(cat_totals.get(i, 0) for i in [13, 14, 15, 16, 259])
    read_total = cat_totals.get(20, 0)  # 阅读物
    cruise_total = cat_totals.get(109, 0)  # 世界巡游

    # 游戏时长:API 返回的是秒,转成小时
    raw_play_time = int(user_data.get("total_play_time", 0) or 0)
    play_time_hours = raw_play_time // 3600 if raw_play_time else 0

    # 探索总览数值(分子/分母), 与线上页面显示口径一致
    # 万相境/丹青屿: resourceMap 刷点聚合优先
    wxj = resource_map.get("万相境", {}) or {}
    dqy = resource_map.get("丹青屿", {}) or {}

    def _rm(region: dict, name: str, key: str, fallback_num: int = 0) -> dict:
        """从 resourceMap 取 {num, total}, 缺失时退回 {fallback_num, 0}"""
        entry = (region or {}).get(name) or {}
        return {
            "num": int(entry.get("awarded", 0) or 0) or fallback_num,
            "total": int(entry.get("total", 0) or 0),
        }

    lantern = _rm(wxj, "奇想华灯", "lantern", _ud_lantern(user_data))
    bell = _rm(wxj, "万相金铃", "bell", _ud_bell(user_data))
    lantern_pillar = _rm(wxj, "流转之柱", "pillar")

    jade = _rm(dqy, "奇想玉琚", "jade", _ud_jade(user_data))
    danqing = _rm(dqy, "丹青玉魄", "danqing", _ud_danqing(user_data))
    dqy_pillar = _rm(dqy, "流转之柱", "pillar")

    # 大地图流转之柱: 分子 = igm.pillar_num(全局), 显示分母 = max(分子, 配置分母)
    pillar_num = _to_int(user_data.get("pillar_num"))
    pillar_config_total = res_max.get("pillar_max", 0)
    pillar_display_total = max(pillar_num, pillar_config_total)
    pillar_completed = pillar_num >= pillar_config_total and pillar_num > 0

    # 从 suitCardListData 计算共鸣统计
    # 优先用 poolStats(复刻前端 A() 的进化口径: 集齐含进化套装, 总数 = 套装数 × 4/2)
    suit_list = state.get("suitCardListData", []) or []
    resonance_data = state.get("reasonaceCardData", {}) or {}
    pool_stats = resonance_data.get("poolStats", {}) or {}
    reso_stats = _compute_reso_stats(suit_list, pool_stats)

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
        # 心愿原野(分子: currency_count 优先 -> igm 字段 -> map 列表长度兜底)
        "whimystar_num": _ud("currency_8") or _ud("whimsystar_num") or star_collected,
        "dew_num": _ud("currency_7") or _ud("dew_num") or dew_collected,
        "pillar_num": pillar_num,
        "permanent_tower": _ud("permanent_tower"),
        "star_sea": _ud("star_sea"),
        # 花焰群岛
        "imagine_ballon_num": _ud("imagine_ballon_num"),
        "flame_light_stone_num": _ud("flame_light_stone_num"),
        # 无忧岛
        "imagine_foam_num": _ud("imagine_foam_num"),
        "worry_free_beads_num": _ud("worry_free_beads_num"),
        # 丹青屿(resourceMap 优先)
        "imagine_jade_num": jade["num"],
        "danqing_jade_num": danqing["num"],
        # 伊赞之土/万相境(resourceMap 优先)
        "imagine_lantern_num": lantern["num"],
        "imagine_bell_num": bell["num"],
        # 伊赞奇想星/露珠(currency_count)
        "whimsystar_yz": _ud("currency_25"),
        "dew_yz": _ud("currency_24"),
        # ---- 分母(exploreResMax 动态值, 兜底为上次验证的版本值) ----
        "whimystar_total": res_max.get("whimsystar_max", 0),
        "dew_total": res_max.get("dew_max", 0),
        # 前端显示口径: 分母 = max(分子, 配置分母), 集满打角标
        "pillar_display_total": pillar_display_total,
        "pillar_config_total": pillar_config_total,
        "pillar_completed": pillar_completed,
        "yz_whimystar_total": res_max.get("yzzt_whimsystar_max", 0),
        "yz_dew_total": res_max.get("yzzt_dew_max", 0),
        "lantern_total": lantern["total"],
        "bell_total": bell["total"],
        "lantern_pillar_num": lantern_pillar["num"],
        "lantern_pillar_total": lantern_pillar["total"],
        "jade_total": jade["total"],
        "danqing_total": danqing["total"],
        "dqy_pillar_num": dqy_pillar["num"],
        "dqy_pillar_total": dqy_pillar["total"],
        "balloon_total": res_max.get("imagine_ballon_max", 0),
        "flame_total": res_max.get("flame_light_stone_max", 0),
        "foam_total": res_max.get("imagine_foam_max", 0),
        "beads_total": res_max.get("worry_free_beads_max", 0),
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
        # 共鸣套装统计(进化口径, 优先 poolStats)
        "limited5_total": reso_stats["limited_5"]["total"],
        "limited5_owned": reso_stats["limited_5"]["collected"],
        "limited5_pieces": reso_stats["limited_5"]["pieces"],
        "limited5_avg": reso_stats["limited_5"]["avg"],
        "limited4_total": reso_stats["limited_4"]["total"],
        "limited4_owned": reso_stats["limited_4"]["collected"],
        "limited4_pieces": reso_stats["limited_4"]["pieces"],
        "limited4_avg": reso_stats["limited_4"]["avg"],
        "permanent5_total": reso_stats["permanent_5"]["total"],
        "permanent5_owned": reso_stats["permanent_5"]["collected"],
        "permanent5_pieces": reso_stats["permanent_5"]["pieces"],
        "permanent5_avg": reso_stats["permanent_5"]["avg"],
        "regions": get_regions(),
        "collected_items": collected_items,
        "user_data": user_data,
        "icon_path": "images/icon",
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _ud_lantern(user_data: dict) -> int:
    return _to_int(user_data.get("imagine_lantern_num"))


def _ud_bell(user_data: dict) -> int:
    return _to_int(user_data.get("imagine_bell_num"))


def _ud_jade(user_data: dict) -> int:
    return _to_int(user_data.get("imagine_jade_num"))


def _ud_danqing(user_data: dict) -> int:
    return _to_int(user_data.get("danqing_jade_num"))


def _compute_reso_stats(
    suit_list: list[dict], pool_stats: dict[str, dict]
) -> dict[str, dict[str, Any]]:
    """共鸣统计: 优先 poolStats(进化口径), 否则从 suitCardListData 兜底估算

    poolStats 结构: {pool_key: {pool_suits, collected, suit_total_num,
                                owned_clothes, total_draw, average_draw_num}}
    """
    keys = ("limited_5", "limited_4", "permanent_5")
    result: dict[str, dict[str, Any]] = {}
    for key in keys:
        ps = pool_stats.get(key) or {}
        if ps.get("pool_suits"):
            result[key] = {
                "total": _to_int(ps.get("suit_total_num")),
                "collected": _to_int(ps.get("collected")),
                "pieces": _to_int(ps.get("owned_clothes")),
                "avg": ps.get("average_draw_num", 0),
            }
            continue
        result[key] = {"total": 0, "collected": 0, "pieces": 0, "avg": 0}

    # poolStats 缺失时, 从 suitCardListData 兜底(旧缓存兼容)
    if not any(r["total"] for r in result.values()):
        stats: dict[str, list[int]] = {
            k: [0, 0, 0] for k in keys
        }  # [套装数, 已共鸣数, 件数]
        total_draws: dict[str, int] = {k: 0 for k in keys}
        for s in suit_list:
            level = int(s.get("level", 5) or 5)
            pool = "permanent" if str(s.get("card_pool_id", "")) == "1" else "limited"
            key = f"{pool}_{level}"
            if key not in stats:
                continue
            stats[key][0] += 1
            collected = int(s.get("collectedCount", 0) or 0)
            total_draw = int(s.get("totalDrawNum", 0) or 0)
            if total_draw > 0 or collected > 0:
                stats[key][1] += 1
            total_draws[key] += total_draw + collected
            stats[key][2] += collected
        for key in keys:
            st, owned, pieces = stats[key]
            draws = total_draws[key]
            result[key] = {
                "total": st,
                "collected": owned,
                "pieces": pieces,
                "avg": round(draws / pieces, 1) if pieces else 0,
            }

    return result


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

        template = NIKI_TEMPLATES.get_template("niki_journal.html")
        html_content = template.render(**context)

        if render_fn:
            return await render_fn(html_content)

        logger.warning("render_fn not provided, returning None")
        return None

    except Exception as e:
        logger.error(f"渲染奇想手账卡片失败: {e}")
        return None
