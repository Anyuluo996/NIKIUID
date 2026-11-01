"""抽卡命令分发与临时网页 payload 测试。

覆盖:
- parser 的 gacha_detail / gacha_page 类型(前缀与 on_command 两条解析路径)
- niki_gacha_page.page_router.build_page_payload 的池子分组/固定资产路径/统计
- create_gacha_page 的 token 缓存与链接生成
"""

import json
import asyncio
from pathlib import Path

import pytest

from gsuid_core.plugins.NIKIUID.NIKIUID.utils.parser import (
    parse_gacha_args_text,
    parse_prefixed_command,
    should_handle_compact_gacha_message,
)
from gsuid_core.plugins.NIKIUID.NIKIUID.niki_gacha_page import page_router


@pytest.fixture(autouse=True)
def _no_icon_download(monkeypatch):
    """屏蔽图标真实下载(测试用假 CDN URL, 不出网)。"""

    async def _noop(urls, folder, limit=0):
        return None

    monkeypatch.setattr(page_router, "download_blessing_icons", _noop)


def _suit(suit_id, level=5, card_type=2, draws=139, avg=14.9,
          cloths_n=10, owned_cloths=10, ts=1700000000):
    cloth_details = []
    for i in range(cloths_n):
        cloth_details.append({
            "clothId": f"1{suit_id}{i:02d}",
            "name": "",
            "displayType": ["头部", "手部", "脚部"][i % 3],
            "image": f"https://cdn.example.com/c_{suit_id}_{i}.png" if i < 2 else "",
            "drawNumFirst": draws if i == 0 else (1 if i < owned_cloths else 0),
            "drawNumSecond": 0,
        })
    return {
        "suit_id": str(suit_id),
        "level": level,
        "card_type": card_type,
        "card_pool_id": "2",
        "name": [{"lang": "zh-cn", "text": f"套装{suit_id}"}],
        "card_pool_name": [{"lang": "zh-cn", "text": f"池{suit_id}"}],
        "preview_image": f"https://cdn.example.com/s_{suit_id}.png",
        "card_start_timestamp": ts,
        "totalDrawNum": draws,
        "averageDrawNum": avg,
        "collectedCount": owned_cloths,
        "evolutionCount": 2,
        "evolutionTotal": 3,
        "cloths": json.dumps([
            {"cloth_id": c["clothId"], "display_type": c["displayType"],
             "image": c["image"]}
            for c in cloth_details
        ]),
        "clothDetails": cloth_details,
    }


def _data(suits, owned_ids=()):
    return {
        "state": {
            "suitCardListData": suits,
            "reasonaceCardData": {"ownedSuitIds": list(owned_ids)},
            "userData": {},
        }
    }


LOGIN_INFO = {"user_info": {"role": {"uid": "101", "nickname": "anyul", "level": 99}}}


def _build(data, tmp_path=""):
    return asyncio.run(page_router.build_page_payload(
        data, LOGIN_INFO, lambda uid: Path(tmp_path) / uid, "https://nik.example.com"
    ))


class TestGachaSubCommandParsing:
    """详情/页面子命令解析"""

    def test_prefixed_detail(self):
        parsed = parse_prefixed_command("nk抽卡详情")
        assert parsed is not None
        assert parsed.kind == "gacha_detail"
        assert parsed.page == 1

    def test_prefixed_detail_page(self):
        parsed = parse_prefixed_command("nk抽卡详情第2页")
        assert parsed.kind == "gacha_detail"
        assert parsed.page == 2

    def test_prefixed_detail_pool(self):
        parsed = parse_prefixed_command("nkck详情4")
        assert parsed.kind == "gacha_detail"
        assert parsed.pool_type == "limited_4"

    def test_prefixed_page_cmd(self):
        parsed = parse_prefixed_command("nk抽卡页面")
        assert parsed.kind == "gacha_page"

    def test_prefixed_web_alias(self):
        parsed = parse_prefixed_command("nkck网页")
        assert parsed.kind == "gacha_page"

    def test_args_text_detail(self):
        """on_command 路径: ev.text 以 详情/页面 开头"""
        parsed = parse_gacha_args_text("详情")
        assert parsed.kind == "gacha_detail"

    def test_args_text_page_digit(self):
        parsed = parse_gacha_args_text("页面2")
        assert parsed.kind == "gacha_page"
        assert parsed.page == 2

    def test_args_text_regression_pool(self):
        parsed = parse_gacha_args_text("4")
        assert parsed.kind == "gacha"
        assert parsed.pool_type == "limited_4"

    def test_prefixed_regression_gacha(self):
        parsed = parse_prefixed_command("nk抽卡4p2")
        assert parsed.kind == "gacha"
        assert parsed.pool_type == "limited_4"
        assert parsed.page == 2

    def test_compact_detail_not_regex_handled(self):
        """nkck详情 由 on_command 路径处理, 不需要正则监听"""
        assert should_handle_compact_gacha_message("nkck详情") is False

    def test_detail_before_gacha_base(self):
        """'抽卡详情' 不能被 '抽卡' 抢先吃掉尾巴"""
        parsed = parse_prefixed_command("niki抽卡详情p3")
        assert parsed.kind == "gacha_detail"
        assert parsed.page == 3


class TestBuildPagePayload:
    """网页全量数据构建"""

    def _mixed_data(self):
        return _data([
            _suit("201", level=5, card_type=2, draws=139, avg=14.9, ts=1700000100),
            _suit("202", level=5, card_type=2, draws=100, avg=10.0, ts=1700000200),
            _suit("301", level=4, card_type=2, draws=50, avg=5.0),
            _suit("401", level=5, card_type=1, draws=60, avg=6.0),
            _suit("501", level=4, card_type=1, draws=40, avg=4.0),
        ], owned_ids=["201", "301"])

    def test_pool_grouping_and_order(self):
        payload = _build(self._mixed_data())
        keys = [p["key"] for p in payload["pools"]]
        assert keys == ["limited_5", "limited_4", "permanent_5", "permanent_4"]
        by_key = {p["key"]: p for p in payload["pools"]}
        assert by_key["limited_5"]["stats"]["total"] == 2
        assert by_key["limited_4"]["stats"]["total"] == 1
        assert by_key["permanent_5"]["stats"]["total"] == 1
        assert by_key["permanent_4"]["stats"]["total"] == 1

    def test_pool_labels(self):
        payload = _build(self._mixed_data())
        by_key = {p["key"]: p for p in payload["pools"]}
        assert by_key["limited_5"]["label"] == "五星限定"
        assert by_key["permanent_4"]["subtitle"] == "常驻四星典藏名录"

    def test_pool_stats(self):
        payload = _build(self._mixed_data())
        by_key = {p["key"]: p for p in payload["pools"]}
        s5 = by_key["limited_5"]["stats"]
        assert s5["owned"] == 1
        assert s5["totalDraws"] == 139 + 100
        assert s5["avgDraws"] == round((139 + 100) / 20, 1)
        assert s5["evolutionCount"] == 4  # 2 套 × 2

    def test_suit_fields_and_asset_urls(self):
        data = _data([
            _suit("202", level=5, card_type=2, draws=100, avg=10.0,
                  ts=1700000200, owned_cloths=4),
        ])
        payload = _build(data)
        suit = payload["pools"][0]["suits"][0]
        assert suit["name"] == "套装202"
        assert suit["preview"].startswith("https://nik.example.com/niki/gacha/asset/suit/")
        assert suit["preview"].endswith(".png")
        assert suit["clothTotal"] == 10
        assert suit["evolutionCount"] == 2
        cloth = suit["cloths"][0]
        assert cloth["image"].startswith(
            "https://nik.example.com/niki/gacha/asset/cloth/"
        )
        assert cloth["owned"] is True
        assert cloth["drawNumFirst"] == 100
        # 未获得且无图的单件: asset URL 为空
        assert suit["cloths"][5]["image"] == ""
        assert suit["cloths"][5]["owned"] is False
        assert suit["cloths"][5]["drawNumFirst"] == 0
        assert suit["ownedClothCount"] == 4

    def test_base_info(self):
        payload = _build(self._mixed_data())
        assert payload["base"]["nickname"] == "anyul"
        assert payload["base"]["uid"] == "101"
        assert payload["base"]["level"] == 99
        assert payload["base"]["avatar"] == ""  # 本地无头像文件
        assert payload["ttlMinutes"] == 10

    def test_empty_state_returns_none(self):
        assert _build({"state": {}}) is None

    def test_no_suits_returns_none(self):
        assert _build(_data([])) is None


class TestCreateGachaPage:
    """token 缓存与链接"""

    def test_create_and_fetch(self, monkeypatch):
        async def fake_url():
            return "https://nik.example.com"

        monkeypatch.setattr(page_router, "_login_page_url", fake_url)
        ok, msg = asyncio.run(page_router.create_gacha_page(
            _data([_suit("201")]), LOGIN_INFO, lambda uid: Path(uid)
        ))
        assert ok is True
        assert "/niki/gacha/" in msg
        assert "10分钟内有效" in msg

        token = msg.split("/niki/gacha/")[1].splitlines()[0].strip()
        payload = page_router._PAGE_CACHE.get(token)
        assert payload is not None
        assert payload["pools"][0]["suits"][0]["name"] == "套装201"

        resp = asyncio.run(page_router.niki_gacha_page_data(token))
        assert resp.status_code == 200
        assert b"limited_5" in resp.body

    def test_expired_data_404(self):
        resp = asyncio.run(page_router.niki_gacha_page_data("nosuchtoken000000"))
        assert resp.status_code == 404

    def test_empty_payload_error(self, monkeypatch):
        async def fake_url():
            return "https://nik.example.com"

        monkeypatch.setattr(page_router, "_login_page_url", fake_url)
        ok, msg = asyncio.run(page_router.create_gacha_page(
            {"state": {}}, LOGIN_INFO, lambda uid: Path(uid)
        ))
        assert ok is False
        assert "nk刷新" in msg


class TestDefaultFilterMode:
    """默认口径"抽到过"(parser 层)"""

    def test_default_is_drawn(self):
        assert parse_gacha_args_text("").filter_mode == "drawn"
        assert parse_gacha_args_text("4").filter_mode == "drawn"

    def test_scope_token_overrides(self):
        assert parse_gacha_args_text("全").filter_mode == "all"
