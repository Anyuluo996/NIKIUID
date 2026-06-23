"""共鸣抽数计算服务

从 note/book/info API 解析 gacha_list 数据，计算各套装的共鸣抽数。

进化套装（suit_id 如 1035501、1035502）贡献基础套装（suit_id 如 10355）的共鸣抽数。
通过 suit/list API 获取所有套装（含进化套装）的 cloth 映射（cloths 字段是 JSON 字符串），
将进化套装的抽数归入其基础套装。
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import aiohttp

from ..constants import CLIENT_ID, MYL_API_BASE

logger = logging.getLogger("niki.draw_num_service")


@dataclass
class GachaRecord:
    """单条抽卡记录"""
    cloth_id: str
    rarity: str  # "4" 或 "5"
    card_pool_id: str
    times_from_last_five_stars: int
    times_from_last_four_stars: int
    pool_cnt: int  # 累计抽数


@dataclass
class SuitDrawInfo:
    """套装共鸣抽数信息"""
    suit_id: str
    total_draw_num: int  # 总共鸣次数
    average_draw_num: float  # 平均共鸣次数
    collected_count: int  # 已拥有衣服数（drawNum > 0）
    draw_nums: list[int]  # 每件衣服的 drawNum 列表


# 进化套装 suit_id 末尾 2 位表示进化序号，前 5 位是基础套装 suit_id
_EVOLUTION_SUIT_PATTERN = re.compile(r"^(\d{5})(\d{2})$")


def decompress_snappy_payload(raw: bytes) -> bytes:
    """解压 snappy 数据，兼容不同实现的 API 名称。"""
    try:
        import snappy
    except ImportError as exc:
        raise ImportError("snappy 未安装，请运行: pip install python-snappy") from exc

    for method_name in ("uncompress", "decompress"):
        method = getattr(snappy, method_name, None)
        if callable(method):
            return method(raw)

    module_file = getattr(snappy, "__file__", None)
    location = f"（当前模块: {module_file}）" if module_file else ""
    raise RuntimeError(
        "检测到错误的 snappy 模块，请卸载 snappy 并安装 python-snappy" + location
    )


async def parse_note_book_info(
    token: str,
    openid: str,
    client_id: int | None = None,
) -> dict[str, SuitDrawInfo] | None:
    """解析 note/book/info API，计算各套装共鸣抽数

    从 info_from_gm 获取所有套装（含进化套装）的 cloth 映射，
    将进化套装的抽数归入其基础套装（suit_id 前 5 位）。

    Args:
        token: 登录 token
        openid: 用户 openid
        client_id: 客户端ID

    Returns:
        {suit_id: SuitDrawInfo} 字典，失败返回 None
    """
    cid = client_id or CLIENT_ID

    try:
        from ..auth.passport import myl_sign_params

        params = myl_sign_params({
            "client_id": cid,
            "token": token,
            "openid": openid,
        })

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{MYL_API_BASE}/v1/strategy/user/note/book/info",
                json=params,
                headers={"referer": "https://myl.nuanpaper.com/"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"note/book/info API 返回状态码 {resp.status}")
                    return None

                raw = await resp.read()

        return parse_note_book_info_from_raw(raw)

    except ImportError:
        logger.error("snappy 未安装，请运行: pip install python-snappy")
        return None
    except Exception as e:
        logger.error(f"解析 note/book/info 失败: {e}")
        return None


def parse_note_book_info_from_raw(raw: bytes) -> dict[str, SuitDrawInfo] | None:
    """从 note/book/info 的原始响应计算共鸣抽数

    接收 snappy 压缩的原始字节数据，解压后计算各套装共鸣抽数。

    Args:
        raw: note/book/info API 返回的原始字节

    Returns:
        {suit_id: SuitDrawInfo} 字典，失败返回 None
    """
    try:
        decompressed = decompress_snappy_payload(raw)
        data = json.loads(decompressed.decode("utf-8"))
        return _compute_draw_info(data)
    except ImportError:
        logger.error("snappy 未安装，请运行: pip install python-snappy")
        return None
    except Exception as e:
        logger.error(f"解析 note/book/info 原始数据失败: {e}")
        return None


def parse_note_book_info_from_decompressed(
    data: dict[str, Any],
) -> dict[str, SuitDrawInfo] | None:
    """从 note/book/info 的已解压数据计算共鸣抽数

    用于复用已解压的数据（避免重复解压）。

    Args:
        data: note/book/info API 返回的已解压 JSON 数据

    Returns:
        {suit_id: SuitDrawInfo} 字典，失败返回 None
    """
    try:
        return _compute_draw_info(data)
    except Exception as e:
        logger.error(f"计算共鸣抽数失败: {e}")
        return None


def parse_note_book_info_with_suit_list(
    note_decompressed: dict[str, Any],
    suit_list: list[dict],
) -> dict[str, SuitDrawInfo] | None:
    """从 note/book/info + suit/list 计算共鸣抽数

    note_decompressed 提供 gacha_list（抽卡记录），suit_list 提供 cloth→suit 映射。

    Args:
        note_decompressed: note/book/info API 返回的已解压数据
        suit_list: suit/list API 返回的套装列表（含 cloths JSON 字符串字段）

    Returns:
        {suit_id: SuitDrawInfo} 字典，失败返回 None
    """
    try:
        # 从 suit/list 构建 cloth→suit 映射（含进化套装）
        cloth_to_suit = _build_cloth_to_suit_mapping_from_suit_list(suit_list)
        logger.info(f"从 suit/list 构建 cloth→suit 映射: {len(cloth_to_suit)} 个 cloth")

        return _compute_draw_info_with_mapping(note_decompressed, cloth_to_suit)
    except Exception as e:
        logger.error(f"共鸣抽数计算失败: {e}")
        return None


def _build_cloth_to_suit_mapping_from_suit_list(suit_list: list[dict]) -> dict[str, str]:
    """从 suit/list 构建 cloth_id -> suit_id 映射

    suit/list 的 cloths 字段是 JSON 字符串，如 '[{"cloth_id": "1020500126", ...}]'
    进化套装（evolutions1/2/3）的 clothes 共享基础套装，已包含在 cloths 中。
    """
    mapping: dict[str, str] = {}

    for suit in suit_list:
        suit_id = str(suit.get("suit_id", ""))
        if not suit_id:
            continue

        # 解析 cloths 字段（JSON 字符串）
        cloths_raw = suit.get("cloths", "[]")
        if isinstance(cloths_raw, str):
            try:
                cloths_list = json.loads(cloths_raw)
            except Exception:
                cloths_list = []
        else:
            cloths_list = cloths_raw or []

        for cloth in cloths_list:
            if isinstance(cloth, dict):
                cloth_id = str(cloth.get("cloth_id", ""))
                if cloth_id:
                    mapping[cloth_id] = suit_id

    return mapping


def _compute_draw_info_with_mapping(
    data: dict[str, Any],
    cloth_to_suit: dict[str, str],
) -> dict[str, SuitDrawInfo] | None:
    """使用已构建的 cloth→suit 映射计算共鸣抽数"""
    gacha_list = data.get("info_from_self", {}).get("gacha_list", [])
    if not gacha_list:
        logger.warning("note/book/info 未返回 gacha_list")
        return None

    records = _parse_gacha_list(gacha_list)
    cloth_draw_nums = _calculate_cloth_draw_nums(records)

    result = _aggregate_by_suit_with_evolution(cloth_draw_nums, cloth_to_suit)
    logger.info(f"共鸣抽数计算完成，覆盖 {len(result)} 个基础套装")
    return result


def _compute_draw_info(data: dict[str, Any]) -> dict[str, SuitDrawInfo] | None:
    """从 note/book/info 数据计算共鸣抽数（内部函数）

    注意：此函数依赖 info_from_gm.suits 获取 cloth 映射，
    若 info_from_gm 结构不包含 suits 下的 cloths，映射将为空。
    生产环境应使用 parse_note_book_info_with_suit_list。
    """
    gacha_list = data.get("info_from_self", {}).get("gacha_list", [])
    if not gacha_list:
        logger.warning("note/book/info 未返回 gacha_list")
        return None

    info_gm: dict[str, Any] = data.get("info_from_gm", {})
    if not info_gm:
        logger.warning("note/book/info 未返回 info_from_gm")
        return None

    records = _parse_gacha_list(gacha_list)
    cloth_draw_nums = _calculate_cloth_draw_nums(records)
    cloth_to_suit = _build_cloth_to_suit_mapping_from_gm(info_gm)
    logger.info(f"cloth->suit 映射数（info_from_gm）: {len(cloth_to_suit)}")

    result = _aggregate_by_suit_with_evolution(cloth_draw_nums, cloth_to_suit)
    logger.info(f"共鸣抽数计算完成（info_from_gm fallback），覆盖 {len(result)} 个基础套装")
    return result


def _parse_gacha_list(gacha_list: list[dict]) -> list[GachaRecord]:
    """解析 gacha_list 为 GachaRecord 列表"""
    records = []
    for item in gacha_list:
        record = GachaRecord(
            cloth_id=item.get("result", ""),
            rarity=item.get("rarity", "4"),
            card_pool_id=item.get("card_pool_id", ""),
            times_from_last_five_stars=item.get("times_from_last_five_stars", 0),
            times_from_last_four_stars=item.get("times_from_last_four_stars", 0),
            pool_cnt=item.get("pool_cnt", 0),
        )
        records.append(record)
    return records


def _calculate_cloth_draw_nums(records: list[GachaRecord]) -> dict[str, list[int]]:
    """计算每件衣服在各套装中的 drawNum

    返回 {cloth_id: [drawNum1, drawNum2, ...]}，每个 drawNum 对应一次被抽到。
    同一件衣服可能被多次抽到（重抽）。
    """
    # {cloth_id: [(rarity, times, pool_cnt), ...]}
    cloth_records: dict[str, list[tuple]] = {}

    for record in records:
        if not record.cloth_id:
            continue
        if record.cloth_id not in cloth_records:
            cloth_records[record.cloth_id] = []
        cloth_records[record.cloth_id].append((
            record.rarity,
            record.times_from_last_five_stars if record.rarity == "5" else record.times_from_last_four_stars,
            record.pool_cnt,
        ))

    cloth_draw_nums: dict[str, list[int]] = {}
    for cloth_id, recs in cloth_records.items():
        draw_nums = []
        for rarity, times, pool_cnt in recs:
            # times 是从上次五星/四星到本次抽卡的间隔，drawNum 就是这个 times 值
            draw_nums.append(times)
        cloth_draw_nums[cloth_id] = draw_nums

    return cloth_draw_nums


def _build_cloth_to_suit_mapping_from_gm(info_gm: dict[str, Any]) -> dict[str, str]:
    """从 info_from_gm 构建 cloth_id -> suit_id 映射

    info_from_gm 可能格式：
    - {"suits": [{"suit_id": "...", "cloths": [{"cloth_id": "..."}]}]}
    - {"suit_list": [{"suit_id": "...", "cloths": [...]}]}
    - {"suits": [{"id": "...", "cloths": [...]}]}  (id 字段)

    尝试多种 key 名称以兼容不同版本。
    """
    mapping: dict[str, str] = {}

    # 尝试 suits 数组
    suits: list[dict] | None = None
    for suits_key in ("suits", "suit_list", "suitInfo"):
        raw = info_gm.get(suits_key)
        if isinstance(raw, list):
            suits = raw
            break

    if suits is None:
        logger.warning(f"info_from_gm 不包含 suits/suit_list 字段，keys: {list(info_gm.keys())}")
        return mapping

    for suit in suits:
        # suit_id 可能在 "suit_id" 或 "id" 字段
        suit_id = suit.get("suit_id") or suit.get("id") or ""
        if not suit_id:
            continue

        # cloths 可能在 "cloths" 或 "cloth" 或 "clothes"
        cloths_raw = suit.get("cloths") or suit.get("cloth") or suit.get("clothes") or []
        if isinstance(cloths_raw, str):
            try:
                cloths_raw = json.loads(cloths_raw)
            except Exception:
                cloths_raw = []

        for cloth in cloths_raw:
            cloth_id: str = ""
            if isinstance(cloth, dict):
                cloth_id = cloth.get("cloth_id") or cloth.get("id") or ""
            elif isinstance(cloth, str):
                cloth_id = cloth
            if cloth_id:
                mapping[cloth_id] = str(suit_id)

    logger.info(f"从 info_from_gm 构建 cloth->suit 映射: {len(mapping)} 个 cloth")
    return mapping


def _get_base_suit_id(suit_id: str) -> str:
    """从 suit_id 提取基础套装 ID

    进化套装 suit_id 如 1035501 -> 基础套装 10355
    进化套装 suit_id 如 1012602 -> 基础套装 10126
    基础套装 suit_id 如 10355 -> 基础套装 10355（无进化后缀，直接返回）
    """
    m = _EVOLUTION_SUIT_PATTERN.match(suit_id)
    if m:
        return m.group(1)
    return suit_id


def _aggregate_by_suit_with_evolution(
    cloth_draw_nums: dict[str, list[int]],
    cloth_to_suit: dict[str, str],
) -> dict[str, SuitDrawInfo]:
    """按套装汇总抽数数据，并将进化套装归入基础套装

    进化套装的 suit_id 末尾 2 位是进化序号，前 5 位是基础套装 ID。
    进化套装的 drawNum 贡献累加到基础套装的 totalDrawNum 中。
    """
    # {suit_id: [all_draw_nums]}
    raw_suit_draw_nums: dict[str, list[int]] = {}

    for cloth_id, draw_nums in cloth_draw_nums.items():
        suit_id = cloth_to_suit.get(cloth_id)
        if not suit_id:
            continue

        if suit_id not in raw_suit_draw_nums:
            raw_suit_draw_nums[suit_id] = []
        raw_suit_draw_nums[suit_id].extend(draw_nums)

    # 先计算每个 suit_id 的原始数据
    raw_info: dict[str, SuitDrawInfo] = {}
    for suit_id, draw_nums in raw_suit_draw_nums.items():
        # 所有 times 都计入：times=0（第一抽就出了）也算 1 抽
        total = sum(draw_nums)
        count = len(draw_nums)
        # 实际抽数 = times + 1，每次抽出都算 1 抽
        # 用 1.0 确保浮点除法，避免 round() 返回整数导致小数丢失
        avg = round((total + count) / 1.0 / count, 1) if count > 0 else 0.0

        raw_info[suit_id] = SuitDrawInfo(
            suit_id=suit_id,
            total_draw_num=total,
            average_draw_num=avg,
            collected_count=count,
            draw_nums=draw_nums,
        )

    # 将进化套装贡献合并到基础套装
    # {base_suit_id: [所有进化套装 + 基础套装自己的 draw_nums]}
    base_draw_nums: dict[str, list[int]] = {}

    for suit_id, info in raw_info.items():
        base_id = _get_base_suit_id(suit_id)
        if base_id not in base_draw_nums:
            base_draw_nums[base_id] = []
        base_draw_nums[base_id].extend(info.draw_nums)

    # 计算合并后的结果
    result: dict[str, SuitDrawInfo] = {}
    for base_id, draw_nums in base_draw_nums.items():
        # 所有 times 都计入：times=0（第一抽就出了）也算 1 抽
        total = sum(draw_nums)
        count = len(draw_nums)
        # 实际抽数 = times + 1，每次抽出都算 1 抽
        # 用 1.0 确保浮点除法，避免 round() 返回整数导致小数丢失
        avg = round((total + count) / 1.0 / count, 1) if count > 0 else 0.0

        result[base_id] = SuitDrawInfo(
            suit_id=base_id,
            total_draw_num=total,
            average_draw_num=avg,
            collected_count=count,
            draw_nums=draw_nums,
        )

    return result


def merge_draw_info_to_suit_card_list(
    suit_card_list: list[dict],
    draw_info_map: dict[str, SuitDrawInfo],
) -> list[dict]:
    """将共鸣抽数数据合并到 suitCardListData

    Args:
        suit_card_list: 原始 suit/list API 数据
        draw_info_map: {suit_id: SuitDrawInfo} 映射

    Returns:
        合并后的 suitCardListData
    """
    result = []
    for card in suit_card_list:
        card_copy = dict(card)
        suit_id = str(card.get("suit_id", ""))

        draw_info = draw_info_map.get(suit_id)
        if draw_info:
            card_copy["totalDrawNum"] = draw_info.total_draw_num
            card_copy["averageDrawNum"] = draw_info.average_draw_num
            card_copy["collectedCount"] = draw_info.collected_count
        else:
            card_copy["totalDrawNum"] = 0
            card_copy["averageDrawNum"] = 0.0
            card_copy["collectedCount"] = 0

        result.append(card_copy)

    return result
