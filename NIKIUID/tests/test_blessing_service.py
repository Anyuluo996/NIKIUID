"""祝福闪光矩阵测试 — blessing_service(前端 j() 复刻)。"""

from gsuid_core.plugins.NIKIUID.NIKIUID.utils.parser import (
    CommandParseError,
    parse_gacha_args_text,
    parse_prefixed_command,
)
from gsuid_core.plugins.NIKIUID.NIKIUID.utils.services.blessing_service import (
    _zh_text,
    build_blessing_matrix,
    collect_blessing_icons,
)


def _color(flag, ctype):
    return {"flag": str(flag), "color_type": ctype}


def _item(flag, suit_flag, pos, color_flags):
    return {
        "flag": str(flag),
        "suit_flag": str(suit_flag),
        "position_type": pos,
        "name": [{"lang": "zh-cn", "text": f"单件{flag}"}],
        "color_icons": [{"flag": str(f), "url": f"https://example.com/{f}.png"} for f in color_flags],
    }


def _suit(flag, level=2, sort_weight=1, updated_at="2026-10-08T14:46:48.016+08:00"):
    return {
        "flag": str(flag),
        "suit_level": level,
        "sort_weight": sort_weight,
        "updated_at": updated_at,
        "name": [{"lang": "zh-cn", "text": f"套装{flag}"}],
        "preview_image": "https://example.com/preview.png",
    }


SUIT_ITEMS = [
    _item(101, 39, 1, [1010331, 1010332]),  # 头部: 黄/蓝
    _item(102, 39, 2, [1010331, 1010332]),  # 手部: 黄/蓝
    _item(103, 39, 3, [1010331, 1010332]),  # 脚部: 黄/蓝
]


class TestBuildBlessingMatrix:
    def test_basic_matrix(self):
        colors = [_color(1010331, "黄色"), _color(1010332, "蓝色")]
        owned = [{"magic_ball_id": "101", "magic_ball_color": "1010331"}]
        result = build_blessing_matrix([_suit(39)], SUIT_ITEMS, colors, owned)
        assert len(result["suits"]) == 1
        suit = result["suits"][0]
        assert suit["suitId"] == "39"
        assert suit["rows"] == ["黄色", "蓝色"]
        # 列按 position_type 升序
        assert [c["positionType"] for c in suit["columns"]] == [1, 2, 3]
        # 总格子 2 行 × 3 件
        assert suit["totalCells"] == 6
        # 只有 头部-黄 拥有
        assert suit["cells"][0][0]["owned"] is True
        assert suit["cells"][0][1]["owned"] is False
        assert result["summary"]["ownedCells"] == 1

    def test_rainbow_row_last(self):
        """「彩色」排最后"""
        colors = [
            _color(1, "彩色"),
            _color(2, "黄色"),
            _color(3, "蓝色"),
        ]
        items = [_item(201, 40, 1, [1, 2, 3])]
        result = build_blessing_matrix([_suit(40)], items, colors, [])
        assert result["suits"][0]["rows"] == ["黄色", "蓝色", "彩色"]

    def test_missing_cell(self):
        """手部没有黄色配色 → missing 格子"""
        colors = [_color(1010331, "黄色"), _color(1010332, "蓝色")]
        items = [
            _item(301, 41, 1, [1010331]),  # 头部只有黄色
            _item(302, 41, 2, [1010332]),  # 手部只有蓝色
        ]
        result = build_blessing_matrix([_suit(41)], items, colors, [])
        suit = result["suits"][0]
        # j(): 行 = 第一列单件(头部)的配色, 手部独有的蓝色不产生新行
        assert suit["rows"] == ["黄色"]
        assert suit["cells"][0][0]["missing"] is False  # 头-黄
        assert suit["cells"][0][1]["missing"] is True  # 手-黄 缺

    def test_sort_level_desc(self):
        """suit_level 降序, 同级按 sort_weight 降序(前端复刻)"""
        suits = [_suit(1, level=1), _suit(2, level=2), _suit(3, level=2, sort_weight=2)]
        items = [_item(401, 1, 1, [9]), _item(402, 2, 1, [9]), _item(403, 3, 1, [9])]
        colors = [_color(9, "黄色")]
        result = build_blessing_matrix(suits, items, colors, [])
        assert [s["suitId"] for s in result["suits"]] == ["3", "2", "1"]

    def test_suit_without_items_skipped(self):
        colors = [_color(9, "黄色")]
        result = build_blessing_matrix([_suit(99)], [], colors, [])
        assert result["suits"] == []

    def test_gathered_all(self):
        colors = [_color(9, "黄色")]
        items = [_item(501, 50, 1, [9])]
        owned = [{"magic_ball_id": "501", "magic_ball_color": "9"}]
        result = build_blessing_matrix([_suit(50)], items, colors, owned)
        assert result["suits"][0]["hasGatheredAll"] is True
        assert result["summary"]["gatheredCount"] == 1

    def test_icons_collected(self):
        colors = [_color(1010331, "黄色"), _color(1010332, "蓝色")]
        result = build_blessing_matrix([_suit(39)], SUIT_ITEMS, colors, [])
        urls = collect_blessing_icons(result)
        assert len(urls) == 2  # 两个配色 URL
        assert all(u.startswith("https://example.com/") for u in urls)

    def test_empty_inputs(self):
        result = build_blessing_matrix([], [], [], [])
        assert result["suits"] == []
        assert result["summary"]["cellCount"] == 0


class TestZhText:
    def test_list(self):
        assert _zh_text([{"lang": "zh-cn", "text": "弦中诗"}]) == "弦中诗"

    def test_empty(self):
        assert _zh_text(None) == ""


class TestGachaPageTokens:
    """抽卡命令页码 token"""

    def test_default_page(self):
        parsed = parse_gacha_args_text("")
        assert parsed.page == 1

    def test_pool_only_keeps_page_1(self):
        parsed = parse_gacha_args_text("5")
        assert parsed.pool_type == "limited_5"
        assert parsed.page == 1

    def test_page_digit(self):
        parsed = parse_gacha_args_text("2")
        assert parsed.page == 2

    def test_page_p2(self):
        parsed = parse_gacha_args_text("p2")
        assert parsed.page == 2

    def test_page_ye2(self):
        parsed = parse_gacha_args_text("页2")
        assert parsed.page == 2

    def test_page_di2ye(self):
        parsed = parse_gacha_args_text("第2页")
        assert parsed.page == 2

    def test_pool_plus_page(self):
        parsed = parse_gacha_args_text("4第3页")
        assert parsed.pool_type == "limited_4"
        assert parsed.page == 3

    def test_prefixed_page(self):
        parsed = parse_prefixed_command("nkckp2")
        assert parsed is not None
        assert parsed.kind == "gacha"
        assert parsed.page == 2

    def test_invalid_tail_still_errors(self):
        try:
            parse_gacha_args_text("abc")
            assert False, "should raise"
        except CommandParseError:
            pass
