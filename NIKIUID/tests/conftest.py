"""共享 fixture 和常量。"""

import sys
from pathlib import Path

import pytest

# 确保 gsuid_core 在 sys.path
_GSCORE = Path(__file__).resolve().parents[4]
if str(_GSCORE) not in sys.path:
    sys.path.insert(0, str(_GSCORE))


# ── 体力计算文档实测常量 ──
ENERGY_MAX = 350
ENERGY_REGEN_SECONDS = 300  # 5 分钟/点
# 文档 DATA_FIELDS.md §5.X.2 实测: energy=6, ts=1782091216, now=1782170450 → current=270
DOC_ENERGY = 6
DOC_TIMESTAMP = 1782091216
DOC_NOW = 1782170450
DOC_EXPECTED_CURRENT = 270


@pytest.fixture
def sample_dispatch():
    """4 个派遣任务样例,start_time 各不同。"""
    return [
        {"text": "采蘑菇", "reward_id": "r1", "start_time": 1782090000},
        {"text": "钓鱼", "reward_id": "r2", "start_time": 1782090600},
        {"text": "采集", "reward_id": "r3", "start_time": 1782091200},
        {"text": "狩猎", "reward_id": "r4", "start_time": 1782091800},
    ]


@pytest.fixture
def sample_suit_card():
    """单个套装卡片样例(旧格式 API)。"""
    return {
        "suit_id": "10355",
        "name": [{"text": "初雪"}],
        "card_pool_name": [{"text": "限定"}],
        "preview_image": "https://webstatic.papegames.com/test/10355.png",
        "level": 5,
        "isCollected": True,
        "totalDrawNum": 80,
        "averageDrawNum": 12.5,
        "collectedCount": 6,
    }


@pytest.fixture
def sample_gacha_list():
    """抽卡记录样例。"""
    return [
        {"result": "1020500126", "rarity": "5", "pool_cnt": 10, "times_from_last_five_stars": 10},
        {"result": "1020500126", "rarity": "5", "pool_cnt": 80, "times_from_last_five_stars": 70},
    ]


@pytest.fixture
def sample_suit_list():
    """套装列表(cloths 含 JSON 字符串)。"""
    return [
        {
            "suit_id": "10355",
            "cloths": '[{"cloth_id":"1020500126"},{"cloth_id":"1020500127"}]',
        }
    ]
