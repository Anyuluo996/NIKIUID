"""命令文本解析器。"""

from __future__ import annotations

import re
from typing import Literal
from dataclasses import dataclass

from .models import PoolType, WardrobeFilterMode

CommandKind = Literal["login", "refresh", "card", "help", "gacha", "gacha_detail", "gacha_page"]

_PREFIXES = ("niki", "nk")
_SIMPLE_COMMANDS: dict[str, CommandKind] = {
    "登录": "login",
    "dl": "login",
    "刷新": "refresh",
    "sx": "refresh",
    "卡片": "card",
    "kp": "card",
    "": "help",
    "帮助": "help",
    "bz": "help",
}
_GACHA_BASES = ("抽卡", "ck")
# 抽卡详情/抽卡页面: 必须先于 _GACHA_BASES 匹配("抽卡详情" 也以 "抽卡" 开头)
# 列表按长度降序排列, 避免 "详情" 抢先吃掉 "抽卡详情" 的尾巴
_GACHA_SUB_BASES: list[tuple[str, CommandKind]] = sorted(
    [
        ("抽卡详情", "gacha_detail"),
        ("ck详情", "gacha_detail"),
        ("抽卡页面", "gacha_page"),
        ("ck页面", "gacha_page"),
        ("抽卡网页", "gacha_page"),
        ("ck网页", "gacha_page"),
        ("详情", "gacha_detail"),
        ("页面", "gacha_page"),
        ("网页", "gacha_page"),
    ],
    key=lambda item: len(item[0]),
    reverse=True,
)
_GACHA_DISPLAY_TOKENS = {
    "统计": "统计",
    "tj": "统计",
    "记录": "记录",
    "jl": "记录",
}
_GACHA_SCOPE_TOKENS = {
    "全": "all",
    "all": "all",
    "a": "all",
}
_GACHA_POOL_TOKENS: list[tuple[str, PoolType]] = [
    ("常驻五星", "limited_5"),
    ("常驻5星", "limited_5"),
    ("常驻五", "limited_5"),
    ("常驻5", "limited_5"),
    ("常驻四星", "limited_4"),
    ("常驻4星", "limited_4"),
    ("常驻四", "limited_4"),
    ("常驻4", "limited_4"),
    ("五星", "limited_5"),
    ("5星", "limited_5"),
    ("五", "limited_5"),
    ("5", "limited_5"),
    ("四星", "limited_4"),
    ("4星", "limited_4"),
    ("四", "limited_4"),
    ("4", "limited_4"),
    ("w", "limited_5"),
    ("s", "limited_4"),
]
_GACHA_TOKENS = sorted(
    (
        [(token, ("display", value)) for token, value in _GACHA_DISPLAY_TOKENS.items()]
        + [(token, ("scope", value)) for token, value in _GACHA_SCOPE_TOKENS.items()]
        + [(token, ("pool", value)) for token, value in _GACHA_POOL_TOKENS]
    ),
    key=lambda item: len(item[0]),
    reverse=True,
)

_EXACT_GACHA_COMMANDS = {
    "niki抽卡",
    "nk抽卡",
    "niki抽卡统计",
    "nk抽卡统计",
    "niki抽卡记录",
    "nk抽卡记录",
    "nikick",
    "nkck",
    "nikicktj",
    "nkcktj",
    "nikickjl",
    "nkckjl",
    "niki抽卡详情",
    "nk抽卡详情",
    "niki抽卡页面",
    "nk抽卡页面",
    "niki抽卡网页",
    "nk抽卡网页",
}


@dataclass(frozen=True)
class ParsedCommand:
    kind: CommandKind
    pool_type: PoolType = "limited_5"
    # 默认"抽到过"(含未抽齐): ownedSuitIds 只含齐套套装, 会漏掉抽了一部分的
    filter_mode: WardrobeFilterMode = "drawn"
    display_label: str = "统计"
    page: int = 1


class CommandParseError(ValueError):
    """命令解析失败。"""


def parse_prefixed_command(text: str) -> ParsedCommand | None:
    """解析带 niki/nk 前缀的命令文本。"""
    compact_text = _compact(text)
    if not compact_text:
        return None

    prefix, rest = _split_prefix(compact_text)
    if prefix is None:
        return None

    kind = _SIMPLE_COMMANDS.get(rest)
    if kind is not None:
        return ParsedCommand(kind=kind)

    for base, kind in _GACHA_SUB_BASES:
        if rest.startswith(base):
            return _parse_gacha_tail(rest[len(base):], kind)

    for base in _GACHA_BASES:
        if rest.startswith(base):
            tail = rest[len(base):]
            return _parse_gacha_tail(tail)

    return None


def parse_gacha_args_text(text: str) -> ParsedCommand:
    """只解析抽卡参数部分，空文本使用默认五星"抽到过"视图。

    on_command 命令("抽卡"/"ck")已被 gsuid_core 剥离, ev.text 以
    "详情"/"页面" 等子命令词开头时返回对应类型。
    """
    compact = _compact(text)
    for base, kind in _GACHA_SUB_BASES:
        if compact.startswith(base):
            return _parse_gacha_tail(compact[len(base):], kind)
    return _parse_gacha_tail(compact)


def should_handle_compact_gacha_message(text: str) -> bool:
    """判断是否需要走全消息监听的紧凑抽卡解析。"""
    stripped = _strip_command_prefix(text)
    if not stripped or re.search(r"\s", stripped):
        return False

    compact_text = _compact(stripped)
    if compact_text in _EXACT_GACHA_COMMANDS:
        return False

    prefix, rest = _split_prefix(compact_text)
    if prefix is None:
        return False

    if not any(rest.startswith(base) for base in _GACHA_BASES):
        return False

    try:
        parsed = parse_prefixed_command(compact_text)
    except CommandParseError:
        return True

    return parsed is not None and parsed.kind == "gacha"


def build_gacha_parse_error_message() -> str:
    return (
        "抽卡参数无法识别，请使用：\n"
        "nk抽卡[全][4|5|四星|五星] / nk抽卡详情 / nk抽卡页面\n"
        "示例：nk抽卡4、nk抽卡全、nk抽卡详情第2页、nk抽卡页面"
    )


def _parse_gacha_tail(tail: str, kind: CommandKind = "gacha") -> ParsedCommand:
    if not tail:
        return ParsedCommand(kind=kind)

    pool_type: PoolType = "limited_5"
    filter_mode: WardrobeFilterMode = "drawn"
    display_label = "统计"
    page = 1
    seen_pool: PoolType | None = None
    remaining = tail

    while remaining:
        matched = False
        for token, (token_type, token_value) in _GACHA_TOKENS:
            if not remaining.startswith(token):
                continue

            matched = True
            remaining = remaining[len(token):]

            if token_type == "display":
                display_label = str(token_value)
            elif token_type == "scope":
                filter_mode = "all"
            elif token_type == "pool":
                next_pool = token_value
                if seen_pool is not None and seen_pool != next_pool:
                    raise CommandParseError(build_gacha_parse_error_message())
                seen_pool = next_pool
                pool_type = next_pool

            break

        if not matched:
            # 页码 token: p2 / 页2 / 第2页
            page_match = re.match(r"^(?:第?页?p?(\d+)页?|p(\d+))", remaining)
            if page_match:
                parsed_page = int(page_match.group(1) or page_match.group(2))
                if parsed_page >= 1:
                    page = parsed_page
                    remaining = remaining[page_match.end():]
                    if remaining and not remaining.isdigit():
                        # 还有未识别的剩余内容才算错误
                        raise CommandParseError(build_gacha_parse_error_message())
                    matched = True

        if not matched:
            raise CommandParseError(build_gacha_parse_error_message())

    return ParsedCommand(
        kind=kind,
        pool_type=pool_type,
        filter_mode=filter_mode,
        display_label=display_label,
        page=page,
    )


def _split_prefix(text: str) -> tuple[str | None, str]:
    for prefix in _PREFIXES:
        if text.startswith(prefix):
            return prefix, text[len(prefix):]
    return None, text


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", _strip_command_prefix(text))


def _strip_command_prefix(text: str) -> str:
    return text.strip().lstrip("/")
