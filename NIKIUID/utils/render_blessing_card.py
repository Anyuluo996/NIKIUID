"""祝福闪光卡片渲染"""

from typing import Any
from pathlib import Path
from datetime import datetime

from gsuid_core.logger import logger
from gsuid_core.ai_core.trigger_bridge import ai_return

from .resource.RESOURCE_PATH import NIKI_TEMPLATES, USER_DATA_PATH
from .services.blessing_service import (
    build_blessing_matrix,
    collect_blessing_icons,
    download_blessing_icons,
)

# 每页套装数(33 套按 suit_level 降序分页)
PAGE_SIZE = 11

BLESSING_ASSETS_DIR = USER_DATA_PATH / "blessing"

POSITION_LABELS = {1: "头部", 2: "手部", 3: "脚部"}


def _to_file_url(path: Path) -> str:
    return f"file:///{str(path.resolve()).replace(chr(92), '/')}"


def build_blessing_context(
    data: dict,
    login_info: dict | None = None,
    get_user_dir_fn: Any = None,
    page: int = 1,
) -> dict[str, Any] | None:
    """构建祝福闪光模板上下文

    Args:
        data: journal_data 字典(state 需含 magicBallData / magicBallList)
        login_info: 登录信息
        get_user_dir_fn: 获取用户目录的函数
        page: 页码(1 起)

    Returns:
        模板上下文; 数据不存在(旧缓存未刷新)返回 None
    """
    state = data.get("state", {})
    mb_data = state.get("magicBallData") or {}
    suit_list = mb_data.get("magicBallSuitList") or []
    item_list = mb_data.get("magicBallItemList") or []
    color_list = mb_data.get("magicBallColorList") or []
    owned_list = state.get("magicBallList") or []

    if not suit_list:
        logger.warning("[blessing] 缓存中无 magicBallData, 需要刷新数据")
        return None

    matrix = build_blessing_matrix(suit_list, item_list, color_list, owned_list)
    suits = matrix["suits"]
    if not suits:
        return None

    total_pages = max(1, (len(suits) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    page_suits = suits[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    # 本地化图标: 球图标 + 套装预览图(下载缓存到 USER_DATA_PATH/blessing)
    icon_urls = collect_blessing_icons({"suits": page_suits})
    preview_urls = [s["previewImage"] for s in page_suits if s.get("previewImage")]

    async def _localize() -> dict[str, str]:
        mapping = await download_blessing_icons(icon_urls, BLESSING_ASSETS_DIR)
        mapping.update(await download_blessing_icons(preview_urls, BLESSING_ASSETS_DIR))
        return mapping

    return {
        "matrix": matrix,
        "page_suits": page_suits,
        "page": page,
        "total_pages": total_pages,
        "icon_map_promise": _localize,
        "login_info": login_info,
        "get_user_dir_fn": get_user_dir_fn,
    }


def _ai_return_blessing(ctx: dict) -> None:
    """提取祝福闪光收集统计,通过 ai_return 返回给 AI 分析"""
    try:
        matrix = ctx.get("matrix", {}) or {}
        summary = matrix.get("summary", {}) or {}
        parts = [
            "【无限暖暖 祝福闪光】",
            f"共 {summary.get('suitCount', 0)} 套"
            f" {summary.get('itemCount', 0)} 件"
            f" {summary.get('cellCount', 0)} 格,"
            f"已集 {summary.get('ownedCells', 0)} 格,"
            f"集齐 {summary.get('gatheredCount', 0)} 套",
            f"当前第 {ctx.get('page', 1)}/{ctx.get('total_pages', 1)} 页:",
        ]
        for suit in ctx.get("page_suits", []) or []:
            name = suit.get("name", "?")
            owned = int(suit.get("ownedCells", 0) or 0)
            total = int(suit.get("totalCells", 0) or 0)
            done = "✓" if suit.get("hasGatheredAll") else ""
            parts.append(f"  - {name} {owned}/{total} {done}")
        ai_return("\n".join(parts))
    except Exception as e:
        logger.warning(f"[NIKIUID] ai_return 祝福闪光数据提取失败: {e}")


async def render_blessing_card(
    data: dict,
    login_info: dict | None = None,
    get_user_dir_fn: Any = None,
    render_fn: Any = None,
    page: int = 1,
) -> str | None:
    """渲染祝福闪光卡片

    Args:
        data: journal_data 字典
        login_info: 登录信息
        get_user_dir_fn: 获取用户目录的函数
        render_fn: HTML 渲染函数
        page: 页码(1 起)

    Returns:
        截图文件路径, 失败返回 None
    """
    try:
        ctx = build_blessing_context(data, login_info, get_user_dir_fn, page)
        if ctx is None:
            return None

        # 数据已拿到、图片未生成,给 AI 注入文字摘要(普通触发时静默)
        _ai_return_blessing(ctx)

        icon_map = await ctx["icon_map_promise"]()

        def _local(url: str) -> str:
            name = icon_map.get(url or "")
            if name:
                return _to_file_url(BLESSING_ASSETS_DIR / name)
            return url or ""

        # 转换渲染数据: 列头/行/格子全部换成模板直接可用的结构
        suits_view = []
        for suit in ctx["page_suits"]:
            rows_view = []
            for row_idx, row_cells in enumerate(suit["cells"]):
                cells_view = []
                for cell in row_cells:
                    if cell.get("missing"):
                        cells_view.append({"state": "missing"})
                    else:
                        cells_view.append(
                            {
                                "state": "owned" if cell["owned"] else "unowned",
                                "icon": _local(cell["icon"]),
                            }
                        )
                rows_view.append({"colorType": suit["rows"][row_idx], "cells": cells_view})
            suits_view.append(
                {
                    "name": suit["name"],
                    "level": suit["suitLevel"],
                    "preview": _local(suit.get("previewImage", "")),
                    "owned": suit["ownedCells"],
                    "total": suit["totalCells"],
                    "gathered": suit["hasGatheredAll"],
                    "column_labels": [POSITION_LABELS.get(c["positionType"], "") for c in suit["columns"]],
                    "rows": rows_view,
                }
            )

        summary = ctx["matrix"]["summary"]

        # 用户信息(与其它卡片一致)
        state = data.get("state", {})
        user_data = state.get("userData", {})
        user_info = (login_info or {}).get("user_info", {})
        role_info = user_info.get("role", {})
        role_id = user_data.get("role_id", role_info.get("uid", ""))

        avatar_path_str = ""
        if get_user_dir_fn and role_id:
            avatar_path = get_user_dir_fn(str(role_id)) / "avatar.png"
            if avatar_path.exists():
                avatar_path_str = _to_file_url(avatar_path)
        if not avatar_path_str:
            avatar_path_str = role_info.get("avatar", "")

        context = {
            "nickname": role_info.get("nickname") or user_data.get("nickname") or "未知",
            "role_id": role_id,
            "level": user_data.get("level", role_info.get("level", 0)),
            "avatar_path": avatar_path_str,
            "suits": suits_view,
            "summary": summary,
            "page": ctx["page"],
            "total_pages": ctx["total_pages"],
            "owned_percent": round(summary["ownedCells"] * 100 / summary["cellCount"], 1)
            if summary["cellCount"]
            else 0,
            "icon_path": "images/icon",
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        template = NIKI_TEMPLATES.get_template("blessing.html")
        html_content = template.render(**context)

        if render_fn:
            return await render_fn(html_content)

        logger.warning("render_fn not provided, returning None")
        return None

    except Exception as e:
        logger.exception(f"渲染祝福闪光卡片失败: {e}")
        return None
