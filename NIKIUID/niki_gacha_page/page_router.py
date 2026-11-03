"""抽卡页面: gsuid_core 内置 FastAPI 路由 + 临时 token 缓存。

参考 XutheringWavesUID wutheringwaves_gachalog/web_view.py 的本地模式与
ww-login /waves/gacha 协议(数据带 TTL, 资产固定路径长缓存):

- 命令 nk抽卡页面 → 构建 payload → PAGE_CACHE(600s) → 返回 /niki/gacha/{token}
- GET /niki/gacha/{token}                页面(no-store)
- GET /niki/gacha/{token}/data           全量抽取数据(no-store)
- GET /niki/gacha/asset/cloth/{fname}    单件图标(固定路径, max-age 7 天)
- GET /niki/gacha/asset/suit/{fname}     套装预览(固定路径, max-age 7 天)
- GET /niki/gacha/asset/avatar/{uid}.png 用户头像(max-age 1 天)

静态资产按内容文件名固定路径, 跨 token / 跨用户可命中浏览器与反代缓存;
页面与数据仅 10 分钟有效, 与登录链接口径一致。

页面图标一律走 WebP 压缩缓存(image_service): 原图最大 7.8MB,
页面显示只有 64~118px, 全量 PNG 会打穿反代/CDN 回源; .png 请求
仍回原图目录(兼容已缓存的旧页面)。
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any, Callable
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

from starlette.responses import FileResponse, HTMLResponse, JSONResponse

from gsuid_core.logger import logger
from gsuid_core.web_app import app

from ..utils.cache import TimedCache
from ..niki_login.login_service import _login_page_url
from ..utils.render_wardrobe_card import (
    SUITS_DIR,
    CLOTHS_DIR,
    build_wardrobe_context,
)
from ..utils.resource.RESOURCE_PATH import NIKI_TEMPLATES, USER_DATA_PATH
from ..utils.services.image_service import (
    WEBP_SUITS_DIR,
    WEBP_CLOTHS_DIR,
    webp_name,
    png_name_of_url,
    bulk_convert_webp,
    convert_png_to_webp,
)
from ..utils.services.blessing_service import bulk_download_icons

GACHA_PAGE_TTL = 600  # 10 分钟, 与登录链接一致

_PAGE_CACHE = TimedCache(timeout=GACHA_PAGE_TTL, maxsize=500)

# (cardType, level) → (key, 标签, 副标题); cardType: 1 常驻 / 2 限定
_POOL_GROUPS: dict[tuple[int, int], tuple[str, str, str]] = {
    (2, 5): ("limited_5", "五星限定", "五星限定典藏名录"),
    (2, 4): ("limited_4", "四星限定", "四星限定典藏名录"),
    (1, 5): ("permanent_5", "常驻五星", "常驻五星典藏名录"),
    (1, 4): ("permanent_4", "常驻四星", "常驻四星典藏名录"),
}
_POOL_ORDER = ["limited_5", "limited_4", "permanent_5", "permanent_4"]


# ----------------------------- payload 构建 -----------------------------


def _asset_fname(url: str) -> str:
    """远程图标 URL → 页面 WebP 资产文件名。"""
    return webp_name(png_name_of_url(url))


def _asset_url(url: str, base_url: str, folder: str) -> str:
    """把图标 URL 映射到固定资产路径(远程 URL 与 file:// 缓存 URL 均取尾文件名)。"""
    if not url:
        return ""
    return f"{base_url}/niki/gacha/asset/{folder}/{quote(_asset_fname(url))}"


def _page_suit(suit: dict[str, Any], base_url: str) -> dict[str, Any]:
    cloths = []
    for c in suit.get("cloths", []) or []:
        cloths.append(
            {
                "clothId": str(c.get("clothId", "") or ""),
                "name": str(c.get("name", "") or ""),
                "displayType": str(c.get("displayType", "") or ""),
                "image": _asset_url(str(c.get("image", "") or ""), base_url, "cloth"),
                "drawNumFirst": int(c.get("drawNumFirst", 0) or 0),
                "drawNumSecond": int(c.get("drawNumSecond", 0) or 0),
                "owned": bool(c.get("owned")),
            }
        )
    return {
        "name": str(suit.get("subSuit", "") or ""),
        "pool": str(suit.get("bigSuit", "") or ""),
        "level": int(suit.get("level", 5) or 5),
        "preview": _asset_url(str(suit.get("imgUrl", "") or ""), base_url, "suit"),
        "totalDrawNum": int(suit.get("totalDrawNum", 0) or 0),
        "avgDrawNum": float(suit.get("avgDrawNum", 0) or 0),
        "collectedCount": int(suit.get("collectedCount", 0) or 0),
        "ownedClothCount": int(suit.get("ownedClothCount", 0) or 0),
        "clothTotal": len(cloths),
        "evolutionCount": int(suit.get("evolutionCount", 0) or 0),
        "evolutionTotal": int(suit.get("evolutionTotal", 0) or 0),
        "isCollected": bool(suit.get("isCollected")),
        # 抽到过(含未抽齐): 网页端只对从未抽到的套装置灰
        "touched": bool(suit.get("isCollected")) or int(suit.get("totalDrawNum", 0) or 0) > 0,
        "cloths": cloths,
    }


def _pool_stats(suits: list[dict[str, Any]]) -> dict[str, Any]:
    collected = sum(s["collectedCount"] for s in suits)
    total_draw = sum(s["totalDrawNum"] for s in suits)
    return {
        "total": len(suits),
        "owned": sum(1 for s in suits if s["isCollected"]),
        "totalDraws": total_draw,
        "avgDraws": round(total_draw / collected, 1) if collected else 0,
        "collected": collected,
        "evolutionCount": sum(s["evolutionCount"] for s in suits),
        "evolutionTotal": sum(s["evolutionTotal"] for s in suits),
    }


async def build_page_payload(
    data: dict,
    login_info: dict | None,
    get_user_dir_fn: Callable[[str], Any],
    base_url: str,
) -> dict[str, Any] | None:
    """构建网页全量数据(五星+四星, 限定+常驻)。无套装数据返回 None。"""
    state = data.get("state", {})
    if not state.get("suitCardListData"):
        return None

    # 按星级取全量(filter_mode=all, 单页装下全部), 复用渲染管线的视图规范化
    level_ctxs = []
    for pool in ("limited_5", "limited_4"):
        ctx = build_wardrobe_context(
            data,
            pool,
            login_info,
            get_user_dir_fn,
            filter_mode="all",
            page=1,
            page_size=10**9,
        )
        if ctx:
            level_ctxs.append(ctx)
    if not level_ctxs:
        return None

    # 预热图标本地缓存(与图片渲染共用目录); 失败不阻塞, 页面用占位图兜底
    cloth_urls: list[str] = []
    suit_urls: list[str] = []
    for ctx in level_ctxs:
        for suit in ctx["clothes"]:
            if suit.get("imgUrl"):
                suit_urls.append(suit["imgUrl"])
            for cloth in suit.get("cloths", []) or []:
                if cloth.get("image"):
                    cloth_urls.append(cloth["image"])
    try:
        if cloth_urls:
            await bulk_download_icons(cloth_urls, CLOTHS_DIR)
        if suit_urls:
            await bulk_download_icons(suit_urls, SUITS_DIR)
    except Exception as e:
        logger.warning(f"[niki抽卡页面] 图标下载失败(页面将显示占位图): {e}")

    # 预转换 WebP 压缩缓存(漏掉的由资产路由按需兜底); 失败不阻塞生成
    try:
        await asyncio.gather(
            bulk_convert_webp([png_name_of_url(u) for u in cloth_urls], CLOTHS_DIR, WEBP_CLOTHS_DIR),
            bulk_convert_webp([png_name_of_url(u) for u in suit_urls], SUITS_DIR, WEBP_SUITS_DIR),
        )
    except Exception as e:
        logger.warning(f"[niki抽卡页面] WebP 压缩失败(路由将按需转换): {e}")

    # 跨星级行聚合后再按固定池序输出(限定五星→限定四星→常驻五星→常驻四星)
    groups: dict[str, list[dict[str, Any]]] = {}
    for ctx in level_ctxs:
        for suit in ctx["clothes"]:
            kind = "permanent" if suit.get("cardType") == 1 else "limited"
            key = f"{kind}_{suit.get('level', 5)}"
            groups.setdefault(key, []).append(_page_suit(suit, base_url))

    pools: list[dict[str, Any]] = []
    for key in _POOL_ORDER:
        suits = groups.get(key)
        if not suits:
            continue
        _, label, subtitle = _POOL_GROUPS[(1 if key.startswith("permanent") else 2, 4 if key.endswith("_4") else 5)]
        pools.append(
            {
                "key": key,
                "label": label,
                "subtitle": subtitle,
                "stats": _pool_stats(suits),
                "suits": suits,
            }
        )

    first = level_ctxs[0]
    role_id = str(first.get("role_id", "") or "")
    avatar_asset = ""
    if role_id:
        avatar_file = USER_DATA_PATH / role_id / "avatar.png"
        if avatar_file.exists():
            avatar_asset = f"{base_url}/niki/gacha/asset/avatar/{quote(role_id)}.png"

    return {
        "version": 1,
        "ttlMinutes": GACHA_PAGE_TTL // 60,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "base": {
            "nickname": str(first.get("nickname", "未知") or "未知"),
            "uid": role_id,
            "level": int(first.get("level", 0) or 0),
            "avatar": avatar_asset,
        },
        "pools": pools,
    }


async def create_gacha_page(
    data: dict,
    login_info: dict | None,
    get_user_dir_fn: Callable[[str], Any],
) -> tuple[bool, str]:
    """生成临时页面: 缓存 payload 并返回给用户的消息文本。"""
    try:
        base_url = (await _login_page_url()).rstrip("/")
        payload = await build_page_payload(data, login_info, get_user_dir_fn, base_url)
    except Exception as e:
        logger.exception(f"[niki抽卡页面] 生成失败: {e}")
        return False, "抽卡页面生成失败, 请稍后再试"

    if payload is None:
        return False, "暂无套装数据可展示, 请先发送 nk刷新 更新数据"

    token = secrets.token_urlsafe(16)
    _PAGE_CACHE.set(token, payload)
    url = f"{base_url}/niki/gacha/{token}"
    logger.info(f"[niki抽卡页面] 已生成 token={token[:6]}*** pools={len(payload['pools'])}")
    return True, (f"抽卡页面已生成(10分钟内有效):\n{url}\n网页内可筛选五星/四星、展开单件明细, 并可一键生成分享图片")


# ----------------------------- 路由 -----------------------------

_EXPIRED_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>页面已过期</title>
<style>
html,body{height:100%;margin:0;background:#efeadb;color:#2e2a22;
font-family:"Noto Serif SC","Source Han Serif SC","STSong","SimSun",serif;
display:flex;align-items:center;justify-content:center;}
.box{padding:34px 40px;border:1px solid #d9cfb4;background:#f9f6ec;max-width:420px;text-align:center;}
h1{font-size:20px;margin:0 0 10px;letter-spacing:4px;}
p{font-size:13px;color:#9a8c6a;line-height:1.8;margin:6px 0;}
code{background:#ece5d2;padding:2px 8px;border-radius:4px;}
</style></head>
<body><div class="box"><h1>页面已过期或不存在</h1>
<p>抽卡页面链接仅在 10 分钟内有效。</p>
<p>请重新发送 <code>nk抽卡页面</code> 获取新链接。</p></div></body></html>"""


def _safe_fname(fname: str) -> bool:
    return (
        bool(fname)
        and len(fname) <= 120
        and "/" not in fname
        and "\\" not in fname
        and ".." not in fname
        # 拒绝盘符相对路径(Windows 下 "C:x" 会在 joinpath 时替换基目录)
        and ":" not in fname
    )


async def _serve_icon(fname: str, src_dir: Path, webp_dir: Path) -> FileResponse | JSONResponse:
    """页面图标: .webp 走压缩缓存(缺则现场转换), 其余回原图目录。"""
    if not _safe_fname(fname):
        return JSONResponse({"error": "bad_request"}, status_code=400)
    if fname.endswith(".webp"):
        path = webp_dir / fname
        if not path.is_file():
            # 按需兜底: 预转换漏掉的(如下载晚于转换)现场补一张
            src = src_dir / (fname[:-5] + ".png")
            if not src.is_file():
                return JSONResponse({"error": "not_found"}, status_code=404)
            if not await asyncio.to_thread(convert_png_to_webp, src, path):
                return JSONResponse({"error": "convert_failed"}, status_code=404)
        return FileResponse(
            path,
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=604800"},
        )
    path = src_dir / fname
    if not path.is_file():
        return JSONResponse({"error": "not_found"}, status_code=404)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=604800"})


@app.get("/niki/gacha/asset/cloth/{fname}")
async def niki_gacha_asset_cloth(fname: str):
    """单件图标(WebP 压缩资产, 固定路径长缓存; .png 兼容旧页面)。"""
    return await _serve_icon(fname, CLOTHS_DIR, WEBP_CLOTHS_DIR)


@app.get("/niki/gacha/asset/suit/{fname}")
async def niki_gacha_asset_suit(fname: str):
    """套装预览图(WebP 压缩资产, 固定路径长缓存; .png 兼容旧页面)。"""
    return await _serve_icon(fname, SUITS_DIR, WEBP_SUITS_DIR)


@app.get("/niki/gacha/asset/avatar/{uid}.png")
async def niki_gacha_asset_avatar(uid: str):
    """用户头像(按 uid 固定路径)。"""
    if not uid.isdigit() or len(uid) > 20:
        return JSONResponse({"error": "bad_request"}, status_code=400)
    path = USER_DATA_PATH / uid / "avatar.png"
    if not path.is_file():
        return JSONResponse({"error": "not_found"}, status_code=404)
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/niki/gacha/{token}/data")
async def niki_gacha_page_data(token: str):
    """网页拉取全量抽取数据(不缓存)。"""
    payload = _PAGE_CACHE.get(token)
    if payload is None:
        return JSONResponse(
            {"error": "expired"},
            status_code=404,
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.get("/niki/gacha/{token}", response_class=HTMLResponse)
async def niki_gacha_page_index(token: str):
    """抽卡页面(含一次性 token, 禁止缓存)。"""
    if _PAGE_CACHE.get(token) is None:
        return HTMLResponse(_EXPIRED_HTML, headers={"Cache-Control": "no-store"})
    try:
        html = NIKI_TEMPLATES.get_template("niki_gacha_page.html").render()
    except Exception as e:
        logger.exception(f"[niki抽卡页面] 模板渲染失败: {e}")
        return HTMLResponse("<h1>template error</h1>", status_code=500)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
