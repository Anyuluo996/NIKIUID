"""抽卡数据处理测试 — draw_num_service 纯函数。"""

from gsuid_core.plugins.NIKIUID.NIKIUID.utils.services.draw_num_service import (
    _get_base_suit_id,
    _build_cloth_to_suit_mapping_from_suit_list,
    _calculate_cloth_draw_nums,
    _aggregate_by_suit_with_evolution,
    merge_draw_info_to_suit_card_list,
    _parse_gacha_list,
    GachaRecord,
    SuitDrawInfo,
)


class TestGetBaseSuitId:
    """进化套装 ID 提取: 7 位 → 5 位基础"""

    def test_seven_digit(self):
        assert _get_base_suit_id("1035501") == "10355"

    def test_five_digit_passthrough(self):
        assert _get_base_suit_id("10355") == "10355"

    def test_too_short(self):
        assert _get_base_suit_id("103") == "103"

    def test_eight_digit_passthrough(self):
        """8 位不匹配正则 → 原样返回"""
        assert _get_base_suit_id("10355001") == "10355001"

    def test_non_digit(self):
        assert _get_base_suit_id("abc") == "abc"

    def test_empty(self):
        assert _get_base_suit_id("") == ""


class TestBuildClothToSuitMapping:
    """cloth_id → suit_id 映射构建"""

    def test_normal(self, sample_suit_list):
        mapping = _build_cloth_to_suit_mapping_from_suit_list(sample_suit_list)
        assert mapping["1020500126"] == "10355"
        assert mapping["1020500127"] == "10355"

    def test_empty_list(self):
        assert _build_cloth_to_suit_mapping_from_suit_list([]) == {}

    def test_missing_cloths(self):
        """套装没有 cloths 字段 → 跳过"""
        result = _build_cloth_to_suit_mapping_from_suit_list(
            [{"suit_id": "99999"}]
        )
        assert result == {}

    def test_malformed_json_cloths(self):
        """cloths JSON 解析失败 → 回退空列表"""
        result = _build_cloth_to_suit_mapping_from_suit_list(
            [{"suit_id": "99999", "cloths": "not json{"}]
        )
        assert result == {}


class TestCalculateClothDrawNums:
    """每个 cloth 的抽数计算"""

    def test_normal(self, sample_gacha_list):
        records = _parse_gacha_list(sample_gacha_list)
        nums = _calculate_cloth_draw_nums(records)
        assert "1020500126" in nums
        assert nums["1020500126"] == [10, 70]

    def test_empty(self):
        assert _calculate_cloth_draw_nums([]) == {}

    def test_skip_empty_cloth_id(self):
        """cloth_id 为空 → 跳过"""
        records = [GachaRecord(
            cloth_id="", rarity="5", card_pool_id="1",
            times_from_last_five_stars=10,
            times_from_last_four_stars=0, pool_cnt=10,
        )]
        assert _calculate_cloth_draw_nums(records) == {}


class TestAggregateBySuitWithEvolution:
    """按套装聚合抽数(含进化合并)"""

    def test_normal_aggregation(self):
        cloth_nums = {"1020500126": [10, 70]}
        cloth_to_suit = {"1020500126": "10355"}
        result = _aggregate_by_suit_with_evolution(cloth_nums, cloth_to_suit)
        assert "10355" in result
        suit = result["10355"]
        assert suit.total_draw_num == 80
        assert suit.collected_count == 2
        assert suit.draw_nums == [10, 70]

    def test_empty_inputs(self):
        assert _aggregate_by_suit_with_evolution({}, {}) == {}

    def test_no_matching_suit(self):
        """cloth 在 cloth_nums 但不在 cloth_to_suit → 跳过"""
        result = _aggregate_by_suit_with_evolution({"x": [1]}, {})
        assert len(result) == 0

    def test_evolution_merge(self):
        """进化套装 1035501 合并到基础套装 10355"""
        cloth_nums = {
            "1020500126": [10, 70],  # 基础套装 cloth
            "1020500127": [5],        # 进化套装 cloth(同基础)
        }
        cloth_to_suit = {
            "1020500126": "10355",
            "1020500127": "1035501",  # 进化 ID
        }
        result = _aggregate_by_suit_with_evolution(cloth_nums, cloth_to_suit)
        # 两个 cloth 都合并到 10355
        assert "10355" in result
        assert "1035501" not in result
        suit = result["10355"]
        assert suit.collected_count == 3  # 2 + 1
        assert suit.total_draw_num == 85  # 80 + 5


class TestMergeDrawInfoToSuitCardList:
    """将抽数信息合并到套装卡片"""

    def test_matched_card(self):
        cards = [{"suit_id": "10355", "name": "初雪"}]
        draw_info = {"10355": SuitDrawInfo(
            suit_id="10355", total_draw_num=80, average_draw_num=40.0,
            collected_count=2, draw_nums=[10, 70],
        )}
        result = merge_draw_info_to_suit_card_list(cards, draw_info)
        assert result[0]["totalDrawNum"] == 80
        assert result[0]["averageDrawNum"] == 40.0
        assert result[0]["collectedCount"] == 2

    def test_unmatched_card_zeros(self):
        """没有抽卡数据的套装 → 零值"""
        cards = [{"suit_id": "99999", "name": "未知"}]
        result = merge_draw_info_to_suit_card_list(cards, {})
        assert result[0]["totalDrawNum"] == 0
        assert result[0]["averageDrawNum"] == 0.0
        assert result[0]["collectedCount"] == 0

    def test_original_not_modified(self):
        """不修改原始卡片"""
        cards = [{"suit_id": "10355"}]
        merge_draw_info_to_suit_card_list(cards, {})
        assert "totalDrawNum" not in cards[0]
