"""套装解析 + 登录 token 测试。"""

import time

from gsuid_core.plugins.NIKIUID.NIKIUID.utils.cache import TimedCache
from gsuid_core.plugins.NIKIUID.NIKIUID.utils.suit_parser import (
    _resolve_pool_type,
    parse_suit_card_list,
    enrich_cards_with_evolutions,
)


class TestResolvePoolType:
    """卡池类型判断

    旧格式用 snake_case (card_time_limit_type / card_pool_id)
    新格式用 camelCase (cardTimeLimitType / cardPoolId)
    """

    def test_permanent_old_format(self):
        card = {"card_time_limit_type": "默认开启", "card_pool_id": "1"}
        assert _resolve_pool_type(card, is_new_format=False) == "permanent"

    def test_limited_old_format(self):
        card = {"card_time_limit_type": "固定时间开启", "card_pool_id": "2"}
        assert _resolve_pool_type(card, is_new_format=False) == "limited"

    def test_permanent_new_format(self):
        card = {"cardTimeLimitType": "默认开启", "cardPoolId": "1"}
        assert _resolve_pool_type(card, is_new_format=True) == "permanent"

    def test_limited_new_format(self):
        card = {"cardTimeLimitType": "固定时间开启", "cardPoolId": "2"}
        assert _resolve_pool_type(card, is_new_format=True) == "limited"

    def test_fallback_by_pool_id(self):
        """没有 time_limit_type,靠 pool_id 判断(1=permanent)"""
        card1 = {"card_pool_id": "1"}
        card2 = {"card_pool_id": "2"}
        assert _resolve_pool_type(card1, is_new_format=False) == "permanent"
        assert _resolve_pool_type(card2, is_new_format=False) == "limited"


class TestEnrichCardsWithEvolutions:
    """进化套装关联"""

    def test_empty_inputs(self):
        """空输入 → 原样返回"""
        result = enrich_cards_with_evolutions(
            [], {}, fix_fn=lambda x: x
        )
        assert result == []

    def test_no_evolution_data(self):
        """resonance_data 为空 → 卡片照原样返回"""
        cards = [{"suit_id": "10355", "name": [{"text": "初雪"}], "level": 5}]
        result = enrich_cards_with_evolutions(cards, {}, fix_fn=lambda x: x)
        assert len(result) >= 1

    def test_with_evolution_data(self):
        """有进化数据 → 不崩溃"""
        cards = [{"suit_id": "10355", "name": [{"text": "初雪"}], "level": 5}]
        resonance = {
            "list": [
                {
                    "evolution_suit_id": "1035501",
                    "evolutions1": '[{"name":"初雪进化","level":5}]',
                }
            ]
        }
        result = enrich_cards_with_evolutions(cards, resonance, fix_fn=lambda x: x)
        assert len(result) >= 1


class TestParseSuitCardList:
    """套装卡片列表解析

    输出键名是英文(bigSuit/subSuit/level/poolType/isCollected/imgUrl 等)
    """

    def test_old_format(self):
        """旧格式 API 解析"""
        cards = [
            {
                "suit_id": "10355",
                "name": [{"text": "初雪"}],
                "card_pool_name": [{"text": "限定"}],
                "preview_image": "https://example.com/10355.png",
                "level": 5,
                "isCollected": True,
            }
        ]
        result = parse_suit_card_list(cards, fix_fn=lambda x: x)
        assert len(result) == 1
        assert result[0]["subSuit"] == "初雪"
        assert result[0]["bigSuit"] == "限定"
        assert result[0]["level"] == 5

    def test_bad_card_skipped(self):
        """解析异常的卡片被跳过,不影响其他"""
        cards = [
            {"suit_id": "10355", "name": [{"text": "初雪"}]},
            "not_a_dict",  # 异常项
            {"suit_id": "10356", "name": [{"text": "星辉"}]},
        ]
        result = parse_suit_card_list(cards, fix_fn=lambda x: x)
        assert len(result) == 2  # 异常项被跳过

    def test_empty_name_skipped(self):
        """name 为空 → 卡片被跳过"""
        cards = [{"suit_id": "10355", "name": []}]
        result = parse_suit_card_list(cards, fix_fn=lambda x: x)
        assert len(result) == 0


class TestTimedCache:
    """TTL 缓存基础行为"""

    def test_set_get(self):
        c = TimedCache(timeout=60, maxsize=10)
        c.set("k1", "v1")
        assert c.get("k1") == "v1"

    def test_get_missing(self):
        c = TimedCache(timeout=60, maxsize=10)
        assert c.get("nope") is None

    def test_ttl_expiry(self):
        """过期后 get 返回 None"""
        c = TimedCache(timeout=0, maxsize=10)  # 0 秒 = 立即过期
        c.set("k1", "v1")
        time.sleep(0.01)
        assert c.get("k1") is None

    def test_lru_eviction(self):
        """超过 maxsize 时淘汰最旧"""
        c = TimedCache(timeout=60, maxsize=2)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)  # 淘汰 a
        assert c.get("a") is None
        assert c.get("b") == 2
        assert c.get("c") == 3

    def test_delete(self):
        c = TimedCache(timeout=60, maxsize=10)
        c.set("k", "v")
        c.delete("k")
        assert c.get("k") is None

    def test_items(self):
        c = TimedCache(timeout=60, maxsize=10)
        c.set("a", 1)
        c.set("b", 2)
        items = c.items()
        assert ("a", 1) in items
        assert ("b", 2) in items

    def test_clear(self):
        c = TimedCache(timeout=60, maxsize=10)
        c.set("a", 1)
        c.clear()
        assert c.get("a") is None
