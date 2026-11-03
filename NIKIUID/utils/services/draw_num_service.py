"""共鸣抽数计算服务

严格复刻奇想手账前端(live_index.a62deecc.js)的共鸣衣橱算法,
2026-11-01 已与线上页面逐项对照验证(10/10 命中,参考 D:\\app\\niki\\docs\\BLESSING_SPARKLE.md §2.1):

  P 构建 : gacha -> card_pool_id -> rarity -> result 分组
  y()    : 对每个 result 组按 pool_cnt 升序取前 2 条
           第 1 条 -> firstSuit, 第 2 条 -> secondSuit
           两组各自 times_from_last_five/four_stars 各 +1
  B()    : 每个 suite 的 cloths 分别匹配 firstSuit/secondSuit 的 result 算 drawNum
  A()    : collected / suitTotalNum / totalOwnedClothesNum / averageDrawNum

关键口径:
- 单件 drawNum = times_from_last_*_stars + 1(前端 y() 里 bump),0 表示未抽到
- 已集齐套数 = |该卡池全部 suit_id + evolutions1/2/3 的 evolution_suit_id ∩ info_from_self.suit_list|
- 套装总数 = 该卡池套装数 × (五星 ? 4 : 2)(五星=初始+3进化, 四星=初始+1进化)
- 件数 = 单件槽位里 drawNum > 0 的个数(firstSuit + secondSuit 两个槽位)
- 每件平均 = 总共鸣数 ÷ 件数
"""

import re
import json
from typing import Any
from collections import defaultdict
from dataclasses import field, asdict, dataclass

import aiohttp

from gsuid_core.logger import logger

from ..constants import CLIENT_ID, MYL_API_BASE

# logger 由 gsuid_core.logger 提供

# 进化套装 suit_id 末尾 2 位表示进化序号，前 5 位是基础套装 suit_id
_EVOLUTION_SUIT_PATTERN = re.compile(r"^(\d{5})(\d{2})$")


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
class ClothDrawInfo:
    """单件共鸣信息(复刻前端 B() 的单件槽位)

    每件衣服在衣橱里占两个槽位: firstSuit(初次共鸣) / secondSuit(重复共鸣)。
    """

    cloth_id: str
    name: str = ""
    display_type: str = ""
    icon: str = ""
    image: str = ""
    draw_num_first: int = 0  # 初次共鸣抽数(0=未抽到)
    draw_num_second: int = 0  # 重复共鸣抽数(0=未重抽)

    @property
    def owned(self) -> bool:
        return self.draw_num_first > 0


@dataclass
class SuitDrawInfo:
    """套装共鸣抽数信息"""

    suit_id: str
    total_draw_num: int = 0  # 总共鸣次数(firstSuit + secondSuit 槽位求和)
    average_draw_num: float = 0.0  # 平均共鸣次数(总共鸣 ÷ 件数槽位)
    collected_count: int = 0  # 已拥有槽位数(drawNum > 0, 含重复共鸣槽位)
    draw_nums: list[int] = field(default_factory=list)  # 每个槽位的 drawNum 列表
    cloths: list[ClothDrawInfo] = field(default_factory=list)  # 单件明细
    evolution_count: int = 0  # 已进化次数(已拥有的 evolution_suit_id 数量)
    evolution_total: int = 0  # 可进化次数(3=五星 / 1=四星)


@dataclass
class PoolDrawStats:
    """卡池级共鸣统计(复刻前端 A())"""

    pool_suits: int = 0  # 该卡池套装数
    collected: int = 0  # 已集齐套数(含进化套装)
    suit_total_num: int = 0  # 套装总数(套装数 × 4/2)
    owned_clothes: int = 0  # 已共鸣件数(drawNum > 0 槽位数)
    total_draw: int = 0  # 总共鸣数
    average_draw_num: float = 0.0  # 每件平均共鸣


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
    raise RuntimeError("检测到错误的 snappy 模块，请卸载 snappy 并安装 python-snappy" + location)


async def parse_note_book_info(
    token: str,
    openid: str,
    client_id: int | None = None,
) -> dict[str, SuitDrawInfo] | None:
    """解析 note/book/info API，计算各套装共鸣抽数

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

        params = myl_sign_params(
            {
                "client_id": cid,
                "token": token,
                "openid": openid,
            }
        )

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
        return parse_note_book_info_from_decompressed(data)
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

    注意: 此路径没有 suit/list 的 cloths 明细, 单件名字/图标为空,
    生产环境应使用 parse_note_book_info_with_suit_list。

    Args:
        data: note/book/info API 返回的已解压 JSON 数据

    Returns:
        {suit_id: SuitDrawInfo} 字典，失败返回 None
    """
    try:
        return compute_draw_info(data.get("info_from_self", {}).get("gacha_list", []), [])
    except Exception as e:
        logger.error(f"计算共鸣抽数失败: {e}")
        return None


def parse_note_book_info_with_suit_list(
    note_decompressed: dict[str, Any],
    suit_list: list[dict],
) -> dict[str, SuitDrawInfo] | None:
    """从 note/book/info + suit/list 计算共鸣抽数

    note_decompressed 提供 gacha_list(抽卡记录)与 suit_list(已拥有),
    suit_list(API) 提供套装 cloths / evolutions 明细。

    Args:
        note_decompressed: note/book/info API 返回的已解压数据
        suit_list: suit/list API 返回的套装列表(含 cloths JSON 字符串字段)

    Returns:
        {suit_id: SuitDrawInfo} 字典，失败返回 None
    """
    try:
        gacha_list = note_decompressed.get("info_from_self", {}).get("gacha_list", [])
        owned_ids = {str(sid) for sid in note_decompressed.get("info_from_self", {}).get("suit_list", [])}
        return compute_draw_info(gacha_list, suit_list, owned_suit_ids=owned_ids)
    except Exception as e:
        logger.error(f"共鸣抽数计算失败: {e}")
        return None


def serialize_pool_stats(
    pool_stats: dict[str, PoolDrawStats],
) -> dict[str, dict]:
    """PoolDrawStats → 纯 dict(字段名不变), 保证可 JSON 落库。

    PoolDrawStats 是 dataclass, 直接放进 state 会让 save_cached_data 的
    json.dumps 抛 "not JSON serializable", 整次刷新数据不落库(生产事故)。
    """
    return {key: asdict(stats) for key, stats in pool_stats.items()}


def compute_pool_stats(
    suit_list: list[dict],
    draw_info_map: dict[str, SuitDrawInfo],
    owned_suit_ids: set[str],
) -> dict[str, PoolDrawStats]:
    """计算卡池级统计(复刻前端 A()),返回 {统计键: PoolDrawStats}

    统计键: limited_5 / limited_4 / permanent_5 / permanent_4。
    口径与线上页面一致: 已集齐含进化套装, 总数 = 套装数 × (五星?4:2)。
    进 state/缓存前必须先经 serialize_pool_stats 转成纯 dict。
    """
    parsed = [_parse_suit(s) for s in suit_list]
    stats: dict[str, PoolDrawStats] = {}

    for key, level, card_type in (
        ("limited_5", 5, 2),
        ("limited_4", 4, 2),
        ("permanent_5", 5, 1),
        ("permanent_4", 4, 1),
    ):
        pool_suits = [p for p in parsed if p["level"] == level and p["card_type"] == card_type]
        if not pool_suits:
            stats[key] = PoolDrawStats()
            continue

        # 已集齐 = |该卡池全部 suit_id + 进化 suit_id ∩ 已拥有|
        all_ids: set[str] = set()
        for p in pool_suits:
            all_ids.add(p["suit_id"])
            all_ids.update(p["evolution_ids"])
        collected = len(all_ids & owned_suit_ids)

        owned_clothes = 0
        total_draw = 0
        for p in pool_suits:
            info = draw_info_map.get(p["suit_id"])
            if info is None:
                continue
            owned_clothes += info.collected_count
            total_draw += info.total_draw_num

        avg = round(total_draw / owned_clothes, 1) if owned_clothes else 0
        stats[key] = PoolDrawStats(
            pool_suits=len(pool_suits),
            collected=collected,
            suit_total_num=len(pool_suits) * (4 if level == 5 else 2),
            owned_clothes=owned_clothes,
            total_draw=total_draw,
            average_draw_num=avg,
        )

    return stats


# ---------------------------------------------------------------------------
# 内部实现
# ---------------------------------------------------------------------------


def _parse_json_field(value: Any, default: Any) -> Any:
    """cloths / evolutionsN 是 JSON 字符串, 解析失败返回 default。"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value if value is not None else default


def _i18n_text(value: Any) -> str:
    """i18n 数组 [{lang, text}] -> zh-cn 文本;双重编码 JSON 也兼容。"""
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("lang") == "zh-cn":
                return str(item.get("text", ""))
        return ""
    if isinstance(value, str):
        try:
            return _i18n_text(json.loads(value))
        except Exception:
            return value
    return ""


def _parse_suit(suit: dict) -> dict:
    """解析套装的 cloths / evolutions 字段(JSON 字符串 -> 结构)。"""
    cloths = _parse_json_field(suit.get("cloths"), []) or []
    evolution_ids: list[str] = []
    evolution_names: list[str] = []
    for key in ("evolutions1", "evolutions2", "evolutions3"):
        evo = _parse_json_field(suit.get(key), None)
        if isinstance(evo, dict) and evo.get("evolution_suit_id"):
            evolution_ids.append(str(evo["evolution_suit_id"]))
            evolution_names.append(_i18n_text(evo.get("evolution_suit_name")))
    return {
        "suit_id": str(suit.get("suit_id", "")),
        "level": int(suit.get("level", 5) or 5),
        "card_type": int(suit.get("card_type", 2) or 2),
        "card_pool_id": str(suit.get("card_pool_id", "")),
        "cloths": [c for c in cloths if isinstance(c, dict)],
        "evolution_ids": evolution_ids,
        "evolution_names": evolution_names,
    }


def _parse_gacha_list(gacha_list: list[dict]) -> list[GachaRecord]:
    """解析 gacha_list 为 GachaRecord 列表"""
    records = []
    for item in gacha_list:
        record = GachaRecord(
            cloth_id=str(item.get("result", "")),
            rarity=str(item.get("rarity", "4")),
            card_pool_id=str(item.get("card_pool_id", "")),
            times_from_last_five_stars=int(item.get("times_from_last_five_stars", 0) or 0),
            times_from_last_four_stars=int(item.get("times_from_last_four_stars", 0) or 0),
            pool_cnt=int(item.get("pool_cnt", 0) or 0),
        )
        records.append(record)
    return records


def _split_two(groups: dict[str, list[GachaRecord]]) -> tuple[list[GachaRecord], list[GachaRecord]]:
    """复刻前端 y(): 每个 result 组按 pool_cnt 升序取前 2 条。

    第 1 条 -> firstSuit, 第 2 条 -> secondSuit,
    两组各自 times_from_last_five/four_stars 各 +1。
    """
    first: list[GachaRecord] = []
    second: list[GachaRecord] = []
    for arr in groups.values():
        s = sorted(arr, key=lambda x: x.pool_cnt)[:2]
        if len(s) >= 1:
            first.append(s[0])
        if len(s) >= 2:
            second.append(s[1])

    def bump(lst: list[GachaRecord]) -> list[GachaRecord]:
        out = []
        for e in sorted(lst, key=lambda x: x.pool_cnt):
            e.times_from_last_five_stars += 1
            e.times_from_last_four_stars += 1
            out.append(e)
        return out

    return bump(first), bump(second)


def _build_first_second_suits(
    gacha_list: list[dict],
) -> dict[str, dict[str, list[GachaRecord]]]:
    """复刻前端 P+y(): {card_pool_id: {rarity: {"first": [...], "second": [...]}}}"""
    records = _parse_gacha_list(gacha_list)
    pool_rar: dict[str, dict[str, dict[str, list[GachaRecord]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for g in records:
        pool_rar[g.card_pool_id][g.rarity][g.cloth_id].append(g)

    pools: dict[str, dict[str, dict[str, list[GachaRecord]]]] = {}
    for pid, rarity_map in pool_rar.items():
        pools[pid] = {}
        for rar in ("5", "4"):
            fs, ss = _split_two(rarity_map.get(rar, {}))
            pools[pid][rar] = {"first": fs, "second": ss}
    return pools


def compute_draw_info(
    gacha_list: list[dict],
    suit_list: list[dict],
    owned_suit_ids: set[str] | None = None,
) -> dict[str, SuitDrawInfo] | None:
    """复刻前端 P/y/B: 计算每个套装的单件共鸣明细与汇总

    Args:
        gacha_list: note/book/info 的 info_from_self.gacha_list
        suit_list: suit/list API 的套装列表(cloths/evolutions 为 JSON 字符串)
        owned_suit_ids: info_from_self.suit_list(已拥有套装, 含进化 id)

    Returns:
        {suit_id: SuitDrawInfo}, 无抽卡记录时返回 None
    """
    if not gacha_list:
        logger.warning("gacha_list 为空, 无法计算共鸣抽数")
        return None

    owned = owned_suit_ids or set()
    pools = _build_first_second_suits(gacha_list)

    result: dict[str, SuitDrawInfo] = {}
    for suit in suit_list:
        p = _parse_suit(suit)
        if not p["suit_id"] or not p["cloths"]:
            continue

        lv = p["level"]
        rar = "5" if lv == 5 else "4"
        tk = "times_from_last_five_stars" if lv == 5 else "times_from_last_four_stars"
        side_records = pools.get(p["card_pool_id"], {}).get(rar, {})
        first_recs = {g.cloth_id: g for g in side_records.get("first", [])}
        second_recs = {g.cloth_id: g for g in side_records.get("second", [])}

        cloths: list[ClothDrawInfo] = []
        draw_nums: list[int] = []
        for cloth in p["cloths"]:
            cloth_id = str(cloth.get("cloth_id", ""))
            first_hit = first_recs.get(cloth_id)
            second_hit = second_recs.get(cloth_id)
            info = ClothDrawInfo(
                cloth_id=cloth_id,
                name=_i18n_text(cloth.get("name")),
                display_type=str(cloth.get("display_type", "") or ""),
                icon=str(cloth.get("icon", "") or ""),
                image=str(cloth.get("image", "") or ""),
                draw_num_first=(getattr(first_hit, tk, 0) if first_hit else 0) or 0,
                draw_num_second=(getattr(second_hit, tk, 0) if second_hit else 0) or 0,
            )
            cloths.append(info)
            draw_nums.extend([info.draw_num_first, info.draw_num_second])

        total = sum(draw_nums)
        count = sum(1 for n in draw_nums if n > 0)
        evo_total = len(p["evolution_ids"])
        evo_owned = sum(1 for eid in p["evolution_ids"] if eid in owned)

        result[p["suit_id"]] = SuitDrawInfo(
            suit_id=p["suit_id"],
            total_draw_num=total,
            average_draw_num=round(total / count, 1) if count else 0.0,
            collected_count=count,
            draw_nums=draw_nums,
            cloths=cloths,
            evolution_count=evo_owned,
            evolution_total=evo_total,
        )

    logger.info(f"共鸣抽数计算完成(前端复刻算法), 覆盖 {len(result)} 个套装")
    return result


def _get_base_suit_id(suit_id: str) -> str:
    """从 suit_id 提取基础套装 ID

    进化套装 suit_id 如 1035501 -> 基础套装 10355
    基础套装 suit_id 如 10355 -> 基础套装 10355(无进化后缀, 直接返回)
    """
    m = _EVOLUTION_SUIT_PATTERN.match(suit_id)
    if m:
        return m.group(1)
    return suit_id


def merge_draw_info_to_suit_card_list(
    suit_card_list: list[dict],
    draw_info_map: dict[str, SuitDrawInfo],
    *,
    with_cloth_details: bool = True,
) -> list[dict]:
    """将共鸣抽数数据合并到 suitCardListData

    合并字段:
    - totalDrawNum / averageDrawNum / collectedCount(兼容旧字段)
    - ownedClothes: drawNum>0 槽位数(与旧 collectedCount 同义, 命名对齐前端)
    - evolutionCount / evolutionTotal: 已进化次数 / 可进化次数
    - clothDetails: 单件明细(cloth_id/name/display_type/image/drawNumFirst/drawNumSecond)
    - evolutionIds: 各进化形态 id(供渲染显示进化名)

    Args:
        suit_card_list: 原始 suit/list API 数据
        draw_info_map: {suit_id: SuitDrawInfo} 映射
        with_cloth_details: 是否携带单件明细(会增大缓存体积)

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
            card_copy["ownedClothes"] = draw_info.collected_count
            card_copy["evolutionCount"] = draw_info.evolution_count
            card_copy["evolutionTotal"] = draw_info.evolution_total
            if with_cloth_details:
                card_copy["clothDetails"] = [
                    {
                        "clothId": c.cloth_id,
                        "name": c.name,
                        "displayType": c.display_type,
                        "image": c.image,
                        "drawNumFirst": c.draw_num_first,
                        "drawNumSecond": c.draw_num_second,
                    }
                    for c in draw_info.cloths
                ]
        else:
            card_copy["totalDrawNum"] = 0
            card_copy["averageDrawNum"] = 0.0
            card_copy["collectedCount"] = 0
            card_copy["ownedClothes"] = 0
            card_copy["evolutionCount"] = 0
            card_copy["evolutionTotal"] = 0

        result.append(card_copy)

    return result
