"""套装数据解析工具"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from gsuid_core.logger import logger

from .encoding import fix_encoding


def _default_logger():
    return logger


def _resolve_pool_type(card: dict[str, Any], is_new_format: bool) -> str:
    """Resolve limited/permanent from documented card metadata."""
    time_limit_key = "cardTimeLimitType" if is_new_format else "card_time_limit_type"
    card_pool_key = "cardPoolId" if is_new_format else "card_pool_id"

    time_limit_type = str(card.get(time_limit_key, "")).strip()
    if time_limit_type == "默认开启":
        return "permanent"
    if time_limit_type == "固定时间开启":
        return "limited"

    return "permanent" if str(card.get(card_pool_key, "")) == "1" else "limited"


def enrich_cards_with_evolutions(
    cards: list,
    resonance_data: dict,
    fix_fn: Callable[[str], str] | None = None,
    logger=None,
) -> list:
    """为原始套装卡片数据添加进化信息（从 resonance_data 补充）

    Args:
        cards: 原始 suitCardListData 列表
        resonance_data: suit/list API 响应（含 evolutions1/2/3 字段）
        fix_fn: 编码修复函数，默认为 fix_encoding
        logger: 日志记录器，默认为 niki.suit_parser
    """
    _fix = fix_fn or fix_encoding

    if not cards or not resonance_data:
        return cards

    # 构建 (name, level) -> evolutions 映射
    evo_by_key: dict[tuple[str, int], list] = {}
    resonance_list = resonance_data.get("list", [])

    for card in resonance_list:
        name_list = card.get("name", [])
        name = name_list[0].get("text", "") if name_list else ""
        name = _fix(name)
        level = card.get("level", 5)
        key = (name, level)
        if key not in evo_by_key:
            evolutions = []
            for evo_key in ["evolutions1", "evolutions2", "evolutions3"]:
                evo_raw = card.get(evo_key, "{}")
                if isinstance(evo_raw, str):
                    try:
                        evo = json.loads(evo_raw)
                        if evo.get("evolution_suit_id"):
                            evolutions.append(evo)
                    except Exception:
                        pass
            evo_by_key[key] = evolutions

    # 补充进化信息到卡片
    enriched = []
    for card in cards:
        name_list = card.get("name", [])
        sub_suit = name_list[0].get("text", "") if name_list else ""
        sub_suit = _fix(sub_suit)
        level = card.get("level", 5)
        key = (sub_suit, level)
        evolutions = evo_by_key.get(key, [])
        enriched_card = dict(card)

        # 确保 isCollected 和 pool_type 字段存在且有效
        total_draw = enriched_card.get("totalDrawNum", 0)
        if not enriched_card.get("isCollected") and total_draw > 0:
            enriched_card["isCollected"] = True

        if not enriched_card.get("pool_type"):
            enriched_card["pool_type"] = _resolve_pool_type(
                enriched_card,
                "suitId" in enriched_card,
            )

        if evolutions:
            enriched_card["evolutions"] = evolutions

        enriched.append(enriched_card)

    return enriched


def parse_suit_card_list(
    suit_card_list: list,
    fix_fn: Callable[[str], str] | None = None,
    logger=None,
) -> list:
    """从 suitCardListData 解析共鸣套装数据

    兼容两种数据格式：
    1. 旧格式（来自 API）：suit_id, name (多语言), card_pool_name, preview_image 等
    2. 新格式（来自浏览器 displayedSuitList 合并）：suitId, name (多语言), image, level, owned, cardPoolId 等

    Args:
        suit_card_list: 从 journal.state.suitCardListData 或合并后的列表
        fix_fn: 编码修复函数，默认为 fix_encoding
        logger: 日志记录器，默认为 niki.suit_parser

    Returns:
        包含各套装数据的列表
    """
    log = logger or _default_logger()
    _fix = fix_fn or fix_encoding

    suits = []

    for card in suit_card_list:
        try:
            is_new_format = "suitId" in card

            # 获取是否已集齐（支持新旧两种格式）
            owned = card.get("owned")
            if owned is not None:
                is_collected = bool(owned)
            else:
                raw_collected = card.get("isCollected")
                total_draw = card.get("totalDrawNum", 0)
                is_collected = bool(raw_collected) or total_draw > 0

            # 获取套装名称
            name_list = card.get("name", [])
            sub_suit = name_list[0].get("text", "") if name_list else ""
            if sub_suit:
                sub_suit = _fix(sub_suit)

            # 获取大套装名称
            if is_new_format:
                pool_type = _resolve_pool_type(card, is_new_format=True)
                big_suit = (
                    "常驻五星"
                    if pool_type == "permanent" and card.get("level") == 5
                    else "常驻四星"
                    if pool_type == "permanent"
                    else "限定五星"
                    if card.get("level") == 5
                    else "限定四星"
                )
            else:
                pool_name_list = card.get("card_pool_name", [])
                big_suit = pool_name_list[0].get("text", "") if pool_name_list else ""
                if big_suit:
                    big_suit = _fix(big_suit)

            # 获取等级
            level = card.get("level", 5)

            # 获取卡池类型
            pool_type = _resolve_pool_type(card, is_new_format=is_new_format)

            # 获取图片 URL
            preview_image = (
                card.get("image", "")
                if is_new_format
                else card.get("preview_image", "")
            )

            # 获取时间戳
            timestamp = card.get("card_start_timestamp", 0)
            if not timestamp and card.get("card_start_time"):
                try:
                    dt = datetime.strptime(card["card_start_time"], "%Y-%m-%d %H:%M:%S")
                    timestamp = int(dt.timestamp())
                except Exception:
                    timestamp = 0

            # 获取共鸣数据
            total_draw = card.get("totalDrawNum", 0)
            avg_draw = card.get("averageDrawNum", 0)

            if not avg_draw and total_draw > 0:
                first_suit = card.get("firstSuit", [])
                if first_suit:
                    avg_draw = round(total_draw / len(first_suit), 1)

            if not total_draw and card.get("extra"):
                try:
                    extra = json.loads(card["extra"])
                    total_draw = extra.get("totalDrawNum", 0)
                    avg_draw = extra.get("averageDrawNum", 0)
                except Exception:
                    pass

            if is_collected and total_draw == 0:
                total_draw = 1

            # 获取进化次数
            evolutions = card.get("evolutions", [])
            if (
                "actualEvolutionCount" in card
                and card["actualEvolutionCount"] is not None
            ):
                evolution_count = int(card["actualEvolutionCount"])
            else:
                evolution_count = len(evolutions) if evolutions else 0

            if sub_suit:
                suits.append(
                    {
                        "bigSuit": big_suit,
                        "subSuit": sub_suit,
                        "level": level,
                        "poolType": pool_type,
                        "avgDrawNum": avg_draw,
                        "totalDrawNum": total_draw,
                        "actualDrawCount": card.get("actualDrawCount", total_draw),
                        "isCollected": is_collected,
                        "imgUrl": preview_image,
                        "timestamp": timestamp,
                        "evolutionCount": evolution_count,
                    }
                )

        except Exception as e:
            if logger:
                logger.warning(f"解析套装数据失败: {e}")
            continue

    log.info(f"解析到 {len(suits)} 个共鸣套装")
    return suits
