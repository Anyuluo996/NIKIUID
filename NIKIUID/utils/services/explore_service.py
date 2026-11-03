"""探索总览数据服务

复刻奇想手账前端(模块 91469 + chunk_39 模块 14338)的探索总览算法,
2026-11-01 已与线上页面 15/15 逐项对照验证
(参考 D:\\app\\niki\\docs\\BLESSING_SPARKLE.md §3):

- 分子: 大地图用 info_from_gm 整数/ currency_count; 子区域(万相境/丹青屿)用
  resourceMap 按刷点逐个计数
- 分母: KV 静态文件 exploreResMax.json(每次版本更新会变, 必须重新拉)
- 万相境/丹青屿的 awarded/total 来自 resourceMap(地图刷点聚合), 不是 igm 字段
- 前端显示分母 = max(分子, 配置分母), 分子 >= 分母时打「已集齐」角标
"""

from __future__ import annotations

import json
from typing import Any
from collections import defaultdict

import aiohttp

from gsuid_core.logger import logger

from ..constants import CLIENT_ID, MYL_API_BASE
from ..auth.passport import myl_sign_params

# exploreResMax.json 的 KV 地址(前端硬编码)
EXPLORE_RES_MAX_URL = "https://assets.papegames.com/kv/2d65c7f3-4ef0-4e93-8ad2-7738b532d8aa/exploreResMax.json"

# resourceMap 覆盖的三个 world_id
WORLD_DQY = "10000010"  # 丹青屿
WORLD_DQZJ = "10000027"  # 丹青之境(与丹青屿合并统计)
WORLD_WXJ = "4020034"  # 万相境

# {区域key: [(world_id, [资源名...]), ...]} —— 丹青屿两个世界的刷点合并
WORLD_PLAN: dict[str, list[tuple[str, list[str]]]] = {
    "万相境": [(WORLD_WXJ, ["奇想华灯", "万相金铃", "流转之柱"])],
    "丹青屿": [
        (WORLD_DQY, ["奇想玉琚", "丹青玉魄", "流转之柱"]),
        (WORLD_DQZJ, ["奇想玉琚", "丹青玉魄", "流转之柱"]),
    ],
}


async def fetch_explore_res_max() -> dict[str, int] | None:
    """拉取探索总览分母静态文件(KV, 不需要登录态)。

    Returns:
        exploreResMax 字典(whimsystar_max 等), 失败返回 None
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                EXPLORE_RES_MAX_URL,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"[explore] exploreResMax 拉取失败: HTTP {resp.status}")
                    return None
                payload = await resp.json(content_type=None)
        res_max = payload.get("exploreResMax")
        if isinstance(res_max, dict):
            logger.info(f"[explore] exploreResMax 拉取成功: {res_max}")
            return {k: int(v) for k, v in res_max.items() if str(v).isdigit()}
        return None
    except Exception as e:
        logger.warning(f"[explore] exploreResMax 拉取异常: {e}")
        return None


def _parse_catalog_name(raw: Any) -> str:
    """catalog 的 name 是双重编码的 JSON 字符串, 最多解 3 层后取 zh-cn。"""
    value = raw
    for _ in range(3):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except ValueError:
            return str(value)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("lang") == "zh-cn":
                return str(item.get("text", ""))
        return str(value)
    return str(value)


def build_resource_map(
    catalog_lists: dict[str, list[dict]],
    spawner_lists: dict[str, list[dict]],
    stages: dict[str, list[dict]],
    obtained_ids: set,
) -> dict[str, dict[str, dict[str, int]]]:
    """复刻前端模块 91469: 构建 {区域: {资源名: {total, awarded}}}

    Args:
        catalog_lists: {world_id: catalog/list 的 data} —— 用 list[0]+list[1] 的 catalogs
        spawner_lists: {world_id: spawner/list 的 list}
        stages: stage/spawner/list 的 stages 字典 {stage_id: [marker]}
        obtained_ids: map/user/info 的 star ∪ dewdrop ∪ pillar ID 集合
    """
    # 每个世界的 catalog 字典(前端只取前两个分组的 catalogs)
    name_by_id: dict[str, str] = {}
    ids_by_name: dict[str, dict[str, str]] = {}
    for world, cat_data in catalog_lists.items():
        arr = []
        groups = (cat_data or {}).get("list") or []
        for group in groups[:2]:
            for item in group.get("catalogs") or []:
                name = _parse_catalog_name(item.get("name"))
                cid = item.get("id")
                arr.append({"id": cid, "name": name})
                if cid is not None:
                    name_by_id[str(cid)] = name
        ids_by_name[world] = {c["name"]: c["id"] for c in arr}

    resource_map: dict[str, dict[str, dict[str, int]]] = {}
    for region_key, plan in WORLD_PLAN.items():
        # {catalog_id: [spawner]} —— 跨 world 合并
        merged: dict[str, list[dict]] = defaultdict(list)
        for world, names in plan:
            entries = list(spawner_lists.get(world) or [])
            # 主刷点里 stage_id 匹配的作模板, 追加 stage 刷点(覆盖 id/catalog)
            for stage_id, markers in (stages or {}).items():
                template = next(
                    (s for s in entries if str(s.get("stage_id")) == str(stage_id)),
                    None,
                )
                if template is None:
                    continue
                for marker in markers or []:
                    entries.append(
                        {
                            **template,
                            "id": marker.get("id"),
                            "catalog": marker.get("catalog"),
                        }
                    )
            ids = {
                str(ids_by_name.get(world, {}).get(n)) for n in names if ids_by_name.get(world, {}).get(n) is not None
            }
            for entry in entries:
                if str(entry.get("catalog")) in ids:
                    merged[str(entry["catalog"])].append(entry)

        out: dict[str, dict[str, int]] = {}
        for cid, spawners in merged.items():
            name = name_by_id.get(cid, cid)
            awarded = sum(1 for s in spawners if s.get("id") in obtained_ids)
            out[name] = {"total": len(spawners), "awarded": awarded}
        resource_map[region_key] = out

    return resource_map


async def fetch_resource_map(
    token: str,
    openid: str,
    client_id: int | None = None,
    map_user_info: dict[str, Any] | None = None,
) -> dict[str, dict[str, dict[str, int]]]:
    """拉取地图刷点数据并聚合出 resourceMap(万相境/丹青屿)

    Args:
        token: 登录 token
        openid: 用户 openid
        client_id: 客户端ID
        map_user_info: 已拉取的 map/user/info data(含 star/dewdrop/pillar 列表),
                       传入可省一次请求

    Returns:
        {区域: {资源名: {total, awarded}}}, 失败返回 {}
    """
    cid = client_id or CLIENT_ID
    try:
        base_params = {
            "client_id": cid,
            "token": token,
            "openid": openid,
        }
        catalog_lists: dict[str, list[dict]] = {}
        spawner_lists: dict[str, list[dict]] = {}
        stages: dict[str, list[dict]] = {}

        async with aiohttp.ClientSession() as session:
            # stage 刷点(室内关卡)
            try:
                stage_data = myl_sign_params(base_params.copy())
                async with session.post(
                    f"{MYL_API_BASE}/v1/strategy/map/stage/spawner/list",
                    json=stage_data,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        raw = await resp.read()
                        stages = _decode_snappy_json(raw).get("stages") or {}
            except Exception as e:
                logger.warning(f"[explore] stage/spawner/list 失败: {e}")

            # 每个 world 的 catalog + spawner
            for world in (WORLD_DQY, WORLD_DQZJ, WORLD_WXJ):
                try:
                    cat_data = myl_sign_params(base_params.copy())
                    async with session.post(
                        f"{MYL_API_BASE}/v1/strategy/map/catalog/list",
                        json={**cat_data, "world_id": world},
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status == 200:
                            catalog_lists[world] = (await resp.json()).get("data") or {}
                except Exception as e:
                    logger.warning(f"[explore] catalog/list({world}) 失败: {e}")

                try:
                    spawn_data = myl_sign_params(base_params.copy())
                    async with session.post(
                        f"{MYL_API_BASE}/v1/strategy/map/spawner/list",
                        json={**spawn_data, "catalog_type_id": [], "world_id": world},
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status == 200:
                            raw = await resp.read()
                            spawner_lists[world] = _decode_snappy_json(raw).get("list") or []
                except Exception as e:
                    logger.warning(f"[explore] spawner/list({world}) 失败: {e}")

            # map/user/info(已获得的 star/dewdrop/pillar ID 列表)
            info: dict[str, Any] = {}
            if map_user_info:
                info = map_user_info
            else:
                try:
                    mu_data = myl_sign_params(base_params.copy())
                    async with session.post(
                        f"{MYL_API_BASE}/v1/strategy/map/user/info",
                        json=mu_data,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status == 200:
                            info = (await resp.json()).get("data") or {}
                except Exception as e:
                    logger.warning(f"[explore] map/user/info 失败: {e}")

        obtained: set = set()
        for key in ("star", "dewdrop", "pillar"):
            obtained.update(info.get(key) or [])

        resource_map = build_resource_map(catalog_lists, spawner_lists, stages, obtained)
        logger.info(
            "[explore] resourceMap 聚合完成: "
            + ", ".join(f"{region}={res}" for region, res in resource_map.items() if res)
        )
        return resource_map

    except Exception as e:
        logger.warning(f"[explore] resourceMap 聚合失败: {e}")
        return {}


def _decode_snappy_json(raw: bytes) -> dict:
    """解压 Snappy 端点响应为 JSON 字典(复用 draw_num_service 的解压逻辑)。"""
    from .draw_num_service import decompress_snappy_payload

    return json.loads(decompress_snappy_payload(raw).decode("utf-8"))
