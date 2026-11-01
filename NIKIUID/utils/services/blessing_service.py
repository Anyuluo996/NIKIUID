"""祝福闪光(blessingSparkle)数据服务

复刻奇想手账前端(live_index.a62deecc.js @251491)的 j() 矩阵构建逻辑,
2026-11-01 已与线上页面逐格对照验证(弦中诗 15 格 12 拥有完全一致,
参考 D:\\app\\niki\\docs\\BLESSING_SPARKLE.md §1):

- 数据来源: main/suit/list 的 magic_ball_suit_list / magic_ball_item_list /
  magic_ball_color_list 三个字段 + note/book/info 的
  info_from_self.magic_ball_list(用户持有)
- 行 = 第一列单件(按 position_type 最小)的配色,「彩色」排最后
- 列 = 该套装单件,按 position_type 升序(1头部/2手部/3脚部)
- 持有判定: "{单件flag}-{颜色flag}" 在 magic_ball_list 集合中
- 排序: suit_level 降序 -> sort_weight 降序 -> updated_at 降序
"""

from __future__ import annotations

import asyncio
from typing import Any
from pathlib import Path
from datetime import datetime

from gsuid_core.logger import logger
from gsuid_core.utils.download_resource.download_file import download


def _zh_text(node: Any) -> str:
    """多语言数组 -> zh-cn 文本。"""
    if isinstance(node, list):
        for item in node:
            if isinstance(item, dict) and item.get("lang") == "zh-cn":
                return str(item.get("text", ""))
        return ""
    if isinstance(node, dict):
        return str(node.get("text", ""))
    return str(node or "")


def build_blessing_matrix(
    suit_list: list[dict],
    item_list: list[dict],
    color_list: list[dict],
    owned_list: list[dict],
) -> dict[str, Any]:
    """复刻前端 j(): 构建祝福闪光矩阵

    Args:
        suit_list: magic_ball_suit_list
        item_list: magic_ball_item_list
        color_list: magic_ball_color_list
        owned_list: info_from_self.magic_ball_list

    Returns:
        {
          "suits": [每套 {suitId, name, suitLevel, previewImage, columns,
                          rows, cells, ownedCells, totalCells, hasGatheredAll}],
          "summary": {suitCount, itemCount, cellCount, ownedCells, gatheredCount},
        }
        没有套装数据时返回 {"suits": [], "summary": {...全 0}}
    """
    owned: set[str] = set()
    for row in owned_list or []:
        if isinstance(row, dict):
            owned.add(f"{row.get('magic_ball_id')}-{row.get('magic_ball_color')}")
    color_type_of = {
        str(c.get("flag")): str(c.get("color_type") or "")
        for c in color_list or []
        if isinstance(c, dict)
    }

    def _sort_key(suit: dict):
        updated = 0.0
        if suit.get("updated_at"):
            try:
                updated = datetime.fromisoformat(
                    str(suit["updated_at"]).replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                updated = 0.0
        return (
            -(int(suit.get("suit_level") or 0)),
            -(int(suit.get("sort_weight") or 0)),
            -updated,
        )

    suits_out: list[dict] = []
    total_cells = 0
    owned_cells = 0
    total_items = 0

    for suit in sorted(suit_list or [], key=_sort_key):
        suit_flag = str(suit.get("flag"))
        columns = sorted(
            (it for it in (item_list or []) if str(it.get("suit_flag")) == suit_flag),
            key=lambda it: int(it.get("position_type") or 0),
        )
        if not columns:
            continue

        # 行 = 第一列单件的配色类型(去重, 彩色最后)
        rows: list[str] = []
        seen: set[str] = set()
        for icon in columns[0].get("color_icons") or []:
            ctype = color_type_of.get(str(icon.get("flag")))
            if not ctype or ctype in seen:
                continue
            seen.add(ctype)
            rows.append(ctype)
        rows.sort(key=lambda c: (c == "彩色",))

        # 格子 = 配色行 × 单件列
        cells: list[list[dict]] = []
        suit_owned = 0
        for ctype in rows:
            row_cells = []
            for item in columns:
                icon = next(
                    (
                        ic
                        for ic in (item.get("color_icons") or [])
                        if color_type_of.get(str(ic.get("flag"))) == ctype
                    ),
                    None,
                )
                if icon is None:
                    row_cells.append({
                        "icon": "",
                        "colorId": "",
                        "owned": False,
                        "missing": True,
                    })
                    continue
                color_id = str(icon.get("flag"))
                is_owned = f"{item.get('flag')}-{color_id}" in owned
                if is_owned:
                    suit_owned += 1
                row_cells.append({
                    "icon": str(icon.get("url") or ""),
                    "colorId": color_id,
                    "owned": is_owned,
                    "missing": False,
                })
            cells.append(row_cells)

        flat = [c for row in cells for c in row]
        gathered = bool(flat) and all(c["owned"] for c in flat)
        suits_out.append({
            "suitId": suit_flag,
            "suitLevel": int(suit.get("suit_level") or 0),
            "name": _zh_text(suit.get("name")),
            "previewImage": str(suit.get("preview_image") or ""),
            "columns": [
                {
                    "itemId": str(it.get("flag")),
                    "positionType": int(it.get("position_type") or 0),
                    "name": _zh_text(it.get("name")),
                }
                for it in columns
            ],
            "rows": rows,
            "cells": cells,
            "ownedCells": suit_owned,
            "totalCells": len(flat),
            "hasGatheredAll": gathered,
        })
        total_cells += len(flat)
        owned_cells += suit_owned
        total_items += len(columns)

    summary = {
        "suitCount": len(suits_out),
        "itemCount": total_items,
        "cellCount": total_cells,
        "ownedCells": owned_cells,
        "gatheredCount": sum(1 for s in suits_out if s["hasGatheredAll"]),
    }
    logger.info(
        f"[blessing] 矩阵构建完成: {summary['suitCount']} 套 / "
        f"{summary['cellCount']} 格 / 已拥有 {summary['ownedCells']}"
    )
    return {"suits": suits_out, "summary": summary}


def collect_blessing_icons(matrix: dict[str, Any]) -> list[str]:
    """收集矩阵里出现的全部球图标 URL(去重, 保序)。"""
    urls: list[str] = []
    seen: set[str] = set()
    for suit in matrix.get("suits", []):
        for row in suit.get("cells", []):
            for cell in row:
                url = cell.get("icon") or ""
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)
    return urls


async def bulk_download_icons(
    icon_urls: list[str],
    icons_dir: Path,
    chunk_size: int = 40,
    concurrency: int = 8,
    log: Any = logger,
) -> None:
    """分块并发批量下载(已存在的文件由 download_blessing_icons 秒回)。

    用于「下载资源」预热与抽卡页面生成前的素材预热:
    上千张图串行要几分钟, 分块并发(默认 8 路)压到几十秒。
    """
    urls = [u for u in dict.fromkeys(icon_urls) if u]
    if not urls:
        return
    chunks = [
        urls[i:i + chunk_size] for i in range(0, len(urls), chunk_size)
    ]

    async def _run(chunk: list[str]) -> None:
        try:
            await download_blessing_icons(chunk, icons_dir)
        except Exception as e:
            log.warning(f"[blessing] 分块下载失败({len(chunk)} 张): {e}")

    await asyncio.gather(*(_run(c) for c in chunks))


async def download_blessing_icons(
    icon_urls: list[str],
    icons_dir: Path,
    log: Any = logger,
    limit: int = 0,
) -> dict[str, str]:
    """下载祝福闪光球图标到本地, 返回 {url: 本地文件名}。

    已存在的文件直接复用(与套装图下载同款跳过逻辑)。
    """
    icons_dir.mkdir(parents=True, exist_ok=True)
    url_to_name: dict[str, str] = {}
    count = 0
    for url in icon_urls:
        if limit and count >= limit:
            break
        if not url:
            continue
        filename = url.split("/")[-1]
        if not filename:
            continue
        if not filename.endswith(".png"):
            filename += ".png"
        local_path = icons_dir / filename
        if local_path.exists():
            url_to_name[url] = filename
            continue
        try:
            retcode = await download(url, icons_dir, filename, tag="[NIKI][blessing]")
            if retcode == 200:
                url_to_name[url] = filename
                count += 1
            else:
                log.warning(f"[blessing] 图标下载失败 HTTP {retcode}: {url[-30:]}")
        except Exception as e:
            log.warning(f"[blessing] 图标下载异常: {e}")
    return url_to_name
