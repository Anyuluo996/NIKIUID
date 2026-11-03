"""抽卡数据处理测试 — draw_num_service(前端复刻算法)。

算法口径参考 D:\\app\\niki\\docs\\BLESSING_SPARKLE.md §2.1,
2026-11-01 已与线上页面 10/10 对照验证。
"""

from gsuid_core.plugins.NIKIUID.NIKIUID.utils.render_wardrobe_card import (
    build_wardrobe_context,
)
from gsuid_core.plugins.NIKIUID.NIKIUID.utils.services.draw_num_service import (
    GachaRecord,
    _i18n_text,
    _split_two,
    _get_base_suit_id,
    _parse_gacha_list,
    _parse_json_field,
    compute_draw_info,
    compute_pool_stats,
    merge_draw_info_to_suit_card_list,
)


def _rec(cloth_id, times, pool_cnt=0, rarity="5", pool="2"):
    return {
        "result": cloth_id,
        "rarity": rarity,
        "card_pool_id": pool,
        "times_from_last_five_stars": times,
        "times_from_last_four_stars": times,
        "pool_cnt": pool_cnt,
    }


SUIT_CLOTHS = '[{"cloth_id":"1020500126","display_type":"鞋子","image":"https://example.com/a.png"},{"cloth_id":"1020500127","display_type":"袜子","image":"https://example.com/b.png"}]'


def _suit(suit_id="10355", level=5, card_type=2, pool="2", cloths=SUIT_CLOTHS, evo=True):
    suit = {
        "suit_id": suit_id,
        "level": level,
        "card_type": card_type,
        "card_pool_id": pool,
        "cloths": cloths,
    }
    if evo:
        suit["evolutions1"] = '{"evolution_suit_id": "1035501"}'
        suit["evolutions2"] = '{"evolution_suit_id": "1035502"}'
        suit["evolutions3"] = '{"evolution_suit_id": "1035503"}'
    return suit


class TestGetBaseSuitId:
    """进化套装 ID 提取: 7 位 → 5 位基础"""

    def test_seven_digit(self):
        assert _get_base_suit_id("1035501") == "10355"

    def test_five_digit_passthrough(self):
        assert _get_base_suit_id("10355") == "10355"

    def test_too_short(self):
        assert _get_base_suit_id("103") == "103"

    def test_eight_digit_passthrough(self):
        assert _get_base_suit_id("10355001") == "10355001"

    def test_non_digit(self):
        assert _get_base_suit_id("abc") == "abc"

    def test_empty(self):
        assert _get_base_suit_id("") == ""


class TestHelpers:
    """JSON 字段与 i18n 文本解析"""

    def test_parse_json_field_string(self):
        assert _parse_json_field('[{"a":1}]', []) == [{"a": 1}]

    def test_parse_json_field_malformed(self):
        assert _parse_json_field("not json{", []) == []

    def test_parse_json_field_passthrough(self):
        assert _parse_json_field([1, 2], []) == [1, 2]

    def test_i18n_list(self):
        assert _i18n_text([{"lang": "zh-cn", "text": "初雪"}]) == "初雪"

    def test_i18n_double_encoded(self):
        assert _i18n_text('[{"lang": "zh-cn", "text": "初雪"}]') == "初雪"

    def test_i18n_empty(self):
        assert _i18n_text(None) == ""


class TestSplitTwo:
    """前端 y(): 每个 result 组按 pool_cnt 升序取前 2 条, times +1"""

    def test_first_and_second(self):
        records = _parse_gacha_list(
            [
                _rec("1020500126", 10, pool_cnt=10),
                _rec("1020500126", 70, pool_cnt=80),
            ]
        )
        first, second = _split_two({"1020500126": records})
        assert len(first) == 1 and len(second) == 1
        # bump +1
        assert first[0].times_from_last_five_stars == 11
        assert second[0].times_from_last_four_stars == 71

    def test_single_record_only_first(self):
        records = _parse_gacha_list([_rec("1020500126", 10, pool_cnt=10)])
        first, second = _split_two({"1020500126": records})
        assert len(first) == 1 and len(second) == 0

    def test_sorted_by_pool_cnt(self):
        records = _parse_gacha_list(
            [
                _rec("1020500126", 70, pool_cnt=80),
                _rec("1020500126", 10, pool_cnt=10),
            ]
        )
        first, _ = _split_two({"1020500126": records})
        assert first[0].times_from_last_five_stars == 11  # pool_cnt=10 的排第一


class TestComputeDrawInfo:
    """复刻前端 B(): 单件明细 + 汇总 + 进化次数"""

    def test_per_cloth_draw_nums(self):
        gacha = [
            _rec("1020500126", 10, pool_cnt=10),
            _rec("1020500126", 70, pool_cnt=80),
            _rec("1020500127", 15, pool_cnt=25),
        ]
        result = compute_draw_info(gacha, [_suit()])
        assert result is not None
        info = result["10355"]
        cloths = {c.cloth_id: c for c in info.cloths}
        # times +1 后进槽位
        assert cloths["1020500126"].draw_num_first == 11
        assert cloths["1020500126"].draw_num_second == 71
        assert cloths["1020500127"].draw_num_first == 16
        assert cloths["1020500127"].draw_num_second == 0
        # 汇总: 槽位求和
        assert info.total_draw_num == 11 + 71 + 16
        assert info.collected_count == 3  # 3 个非零槽位
        assert info.average_draw_num == round((11 + 71 + 16) / 3, 1)

    def test_cloth_metadata(self):
        result = compute_draw_info([_rec("1020500126", 10)], [_suit()])
        cloth = result["10355"].cloths[0]
        assert cloth.display_type == "鞋子"
        assert cloth.image == "https://example.com/a.png"

    def test_evolution_count(self):
        owned = {"10355", "1035501", "1035502"}  # 本体 + 2 次进化
        result = compute_draw_info([_rec("1020500126", 10)], [_suit()], owned)
        info = result["10355"]
        assert info.evolution_count == 2
        assert info.evolution_total == 3

    def test_rarity_match(self):
        """五星套装只吃 rarity=5 的记录"""
        gacha = [
            _rec("1020500126", 10, rarity="5"),
            _rec("1020500126", 99, rarity="4"),
        ]
        result = compute_draw_info(gacha, [_suit(level=5)])
        cloth = result["10355"].cloths[0]
        assert cloth.draw_num_first == 11
        assert cloth.draw_num_second == 0

    def test_empty_gacha_returns_none(self):
        assert compute_draw_info([], [_suit()]) is None

    def test_pool_isolation(self):
        """不同 card_pool_id 的同名 cloth 不互相干扰"""
        gacha = [
            _rec("1020500126", 10, pool="2"),
            _rec("1020500126", 20, pool="1"),
        ]
        result = compute_draw_info(gacha, [_suit(pool="2")])
        cloth = result["10355"].cloths[0]
        assert cloth.draw_num_first == 11
        assert cloth.draw_num_second == 0


class TestComputePoolStats:
    """复刻前端 A(): 集齐含进化套装, 总数 ×4/×2"""

    def test_five_star_pool(self):
        suits = [
            _suit("10355"),
            _suit("10356", cloths='[{"cloth_id":"1020500128"}]'),
        ]
        info = compute_draw_info([_rec("1020500126", 10)], suits)
        owned = {"10355", "1035501", "1035502", "1035503"}  # 第一套全进化
        stats = compute_pool_stats(suits, info, owned)
        s5 = stats["limited_5"]
        # 2 套 × 4 = 8
        assert s5.suit_total_num == 8
        # 集齐口径: 每个进化 id 单独计数(前端 A() 的 set 交集)
        assert s5.collected == 4
        assert s5.owned_clothes == 1
        assert s5.average_draw_num == 11.0

    def test_four_star_pool(self):
        suits = [_suit("10357", level=4, evo=False, cloths='[{"cloth_id":"1020500128"}]')]
        suits[0]["evolutions1"] = '{"evolution_suit_id": "1035701"}'
        info = compute_draw_info([_rec("1020500128", 5, rarity="4")], suits)
        stats = compute_pool_stats(suits, info, {"10357"})
        s4 = stats["limited_4"]
        assert s4.suit_total_num == 2  # 四星 ×2
        assert s4.collected == 1
        assert s4.owned_clothes == 1

    def test_card_type_separates_pools(self):
        """card_type=1 常驻 / 2 限定"""
        suits = [_suit("10358", card_type=1), _suit("10359", card_type=2)]
        info = compute_draw_info([_rec("1020500126", 10)], suits)
        stats = compute_pool_stats(suits, info, set())
        assert stats["permanent_5"].pool_suits == 1
        assert stats["limited_5"].pool_suits == 1

    def test_empty_pool(self):
        stats = compute_pool_stats([], {}, set())
        assert stats["limited_5"].pool_suits == 0


class TestMergeDrawInfoToSuitCardList:
    """将抽数信息合并到套装卡片"""

    def _info(self):
        from gsuid_core.plugins.NIKIUID.NIKIUID.utils.services.draw_num_service import (
            SuitDrawInfo,
            ClothDrawInfo,
        )

        return SuitDrawInfo(
            suit_id="10355",
            total_draw_num=98,
            average_draw_num=32.7,
            collected_count=3,
            draw_nums=[11, 71, 16],
            cloths=[ClothDrawInfo(cloth_id="1020500126", draw_num_first=11)],
            evolution_count=2,
            evolution_total=3,
        )

    def test_matched_card(self):
        cards = [{"suit_id": "10355", "name": "初雪"}]
        result = merge_draw_info_to_suit_card_list(cards, {"10355": self._info()})
        assert result[0]["totalDrawNum"] == 98
        assert result[0]["averageDrawNum"] == 32.7
        assert result[0]["collectedCount"] == 3
        assert result[0]["evolutionCount"] == 2
        assert result[0]["evolutionTotal"] == 3
        assert result[0]["clothDetails"][0]["clothId"] == "1020500126"
        assert result[0]["clothDetails"][0]["drawNumFirst"] == 11

    def test_without_cloth_details(self):
        cards = [{"suit_id": "10355"}]
        result = merge_draw_info_to_suit_card_list(cards, {"10355": self._info()}, with_cloth_details=False)
        assert "clothDetails" not in result[0]
        assert result[0]["evolutionCount"] == 2

    def test_unmatched_card_zeros(self):
        cards = [{"suit_id": "99999", "name": "未知"}]
        result = merge_draw_info_to_suit_card_list(cards, {})
        assert result[0]["totalDrawNum"] == 0
        assert result[0]["averageDrawNum"] == 0.0
        assert result[0]["collectedCount"] == 0
        assert result[0]["evolutionCount"] == 0
        assert "clothDetails" not in result[0]

    def test_original_not_modified(self):
        cards = [{"suit_id": "10355"}]
        merge_draw_info_to_suit_card_list(cards, {})
        assert "totalDrawNum" not in cards[0]


class TestGachaRecordParsing:
    def test_parse_fields(self):
        records = _parse_gacha_list(
            [
                {
                    "result": "1020500126",
                    "rarity": "5",
                    "card_pool_id": "2",
                    "times_from_last_five_stars": 10,
                    "times_from_last_four_stars": 3,
                    "pool_cnt": 42,
                }
            ]
        )
        assert isinstance(records[0], GachaRecord)
        assert records[0].pool_cnt == 42
        assert records[0].cloth_id == "1020500126"


class TestDrawnFilterMode:
    """默认口径"抽到过": ownedSuitIds 只含齐套套装, 抽了一部分的也要显示"""

    def _data(self, suits, owned_ids):
        return {
            "state": {
                "suitCardListData": suits,
                "reasonaceCardData": {"ownedSuitIds": owned_ids},
                "userData": {},
            }
        }

    def _suit(self, suit_id, draws=0):
        return {
            "suit_id": suit_id,
            "level": 5,
            "card_type": 2,
            "totalDrawNum": draws,
            "name": [{"lang": "zh-cn", "text": suit_id}],
            "card_pool_name": [],
            "cloths": "[]",
        }

    def _names(self, ctx):
        return {c["subSuit"] for c in ctx["clothes"]}

    def test_drawn_includes_partial_suits(self):
        data = self._data(
            [self._suit("甲", 84), self._suit("乙", 0), self._suit("丙", 10)],
            ["丙"],
        )
        ctx = build_wardrobe_context(data, "limited_5", None, None, "drawn", page_size=99)
        assert self._names(ctx) == {"甲", "丙"}  # 乙从未抽到, 不显示

    def test_owned_only_fully_collected(self):
        data = self._data(
            [self._suit("甲", 84), self._suit("丙", 10)],
            ["丙"],
        )
        ctx = build_wardrobe_context(data, "limited_5", None, None, "owned", page_size=99)
        assert self._names(ctx) == {"丙"}

    def test_all_includes_undrawn(self):
        data = self._data(
            [self._suit("甲", 84), self._suit("乙", 0)],
            [],
        )
        ctx = build_wardrobe_context(data, "limited_5", None, None, "all", page_size=99)
        assert self._names(ctx) == {"甲", "乙"}


class TestSerializePoolStats:
    """回归: PoolDrawStats dataclass 直接进 state 会让刷新落库失败(生产事故)"""

    def test_serialize_json_safe(self):
        import json

        from gsuid_core.plugins.NIKIUID.NIKIUID.utils.services.draw_num_service import (
            serialize_pool_stats,
        )

        suits = [_suit("10355"), _suit("10356", cloths='[{"cloth_id":"1020500128"}]')]
        info = compute_draw_info([_rec("1020500126", 10)], suits)
        stats = compute_pool_stats(suits, info, {"10355"})

        blob = json.dumps(serialize_pool_stats(stats), allow_nan=False)
        parsed = json.loads(blob)
        assert parsed["limited_5"]["pool_suits"] == 2
        assert parsed["limited_5"]["suit_total_num"] == 8
        assert parsed["limited_5"]["average_draw_num"] == 11.0

    def test_raw_dataclass_not_json_serializable(self):
        import json

        suits = [_suit("10355")]
        info = compute_draw_info([_rec("1020500126", 10)], suits)
        stats = compute_pool_stats(suits, info, {"10355"})
        try:
            json.dumps(stats)
            raised = False
        except TypeError:
            raised = True
        assert raised  # 修复前正是这个异常吞掉了整次刷新落库
