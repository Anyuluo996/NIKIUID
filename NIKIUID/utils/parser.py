"""命令文本解析器。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .models import PoolType, WardrobeFilterMode

CommandKind = Literal["login", "refresh", "card", "help", "gacha"]

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
}


@dataclass(frozen=True)
class ParsedCommand:
    kind: CommandKind
    pool_type: PoolType = "limited_5"
    filter_mode: WardrobeFilterMode = "owned"
    display_label: str = "统计"


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

    for base in _GACHA_BASES:
        if rest.startswith(base):
            tail = rest[len(base):]
            return _parse_gacha_tail(tail)

    return None


def parse_gacha_args_text(text: str) -> ParsedCommand:
    """只解析抽卡参数部分，空文本使用默认五星已共鸣视图。"""
    return _parse_gacha_tail(_compact(text))


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
        "nk抽卡[全][4|5|四星|五星]\n"
        "示例：nk抽卡4、nk抽卡全、nk抽卡记录全、nkckjla"
    )


def _parse_gacha_tail(tail: str) -> ParsedCommand:
    if not tail:
        return ParsedCommand(kind="gacha")

    pool_type: PoolType = "limited_5"
    filter_mode: WardrobeFilterMode = "owned"
    display_label = "统计"
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
            raise CommandParseError(build_gacha_parse_error_message())

    return ParsedCommand(
        kind="gacha",
        pool_type=pool_type,
        filter_mode=filter_mode,
        display_label=display_label,
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
