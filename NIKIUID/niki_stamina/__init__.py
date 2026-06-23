"""NIKIUID 体力查询命令。

nk体力 / niki体力 - 查询活跃能量、朝夕心愿、派遣任务等日常进度。
数据来自 note/book/info 的 info_from_gm 字段。
"""

from __future__ import annotations

import datetime
import time

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment
from gsuid_core.sv import SV

from ..niki_config.niki_config import NikiConfig
from ..utils.database import NikiUser
from ..utils.msgs import CommonMsg, send_niki_notify
from ..utils.render_image import render_html_to_image
from ..utils.resource.RESOURCE_PATH import (
    NIKI_TEMPLATES,
    USER_DATA_PATH,
)
from ..utils.services.stamina_service import fetch_realtime_stamina
from ..utils.storage_cache import load_cached_data

sv_niki_stamina = SV("niki体力")

# 能量上限(满级)
ENERGY_MAX = 350
DAILY_TASK_MAX = 500
# 每个派遣任务的总时长(秒)= 20 小时(参考 docs/API_USAGE.md dispatch 数据源分析)
DISPATCH_TOTAL_SECONDS = 20 * 3600


def _build_stamina_context(user_data: dict, role: dict, avatar_path: str) -> dict:
    """构建体力卡片 Jinja2 上下文。

    user_data 可能来自实时接口(含 estimated_energy/data_timestamp/daily_*)
    或缓存(只有基础字段)。
    """
    energy = int(user_data.get("energy", 0) or 0)
    # 实时接口给出按前端公式计算的当前体力,缓存没有就用基线值
    estimated_energy = int(user_data.get("estimated_energy", energy) or 0)
    daily_task = int(user_data.get("daily_task", 0) or 0)
    daily_task_max = int(user_data.get("daily_task_max", DAILY_TASK_MAX) or DAILY_TASK_MAX)
    daily_countdown = user_data.get("daily_countdown", "")
    daily_reset = bool(user_data.get("daily_reset", False))
    star_sea = int(user_data.get("star_sea", 0) or 0)
    periodic_tower = int(user_data.get("periodic_tower", 0) or 0)
    dispatch = user_data.get("dispatch", [])
    if not isinstance(dispatch, list):
        dispatch = []

    data_ts = int(user_data.get("data_timestamp", 0) or 0)
    data_age_h = float(user_data.get("data_age_hours", 0) or 0)
    human_remaining = user_data.get("human_remaining", "")

    energy_pct = min(estimated_energy / ENERGY_MAX * 100, 100) if ENERGY_MAX > 0 else 0
    task_done = "✅ 已完成" if daily_task >= daily_task_max else "进行中"

    # 派遣任务格式化(总时长 20 小时,用 start_time 计算剩余时间)
    now = int(time.time())
    dispatch_list = []
    for d in dispatch:
        if not isinstance(d, dict):
            continue
        text = d.get("text", "未知")
        reward_id = d.get("reward_id", "")
        spend = int(d.get("spend_time", 0) or 0)
        start_ts = int(d.get("start_time", 0) or 0)

        # 用 start_time + 20h 算结束时间,剩余 = 结束 - 当前
        end_ts = start_ts + DISPATCH_TOTAL_SECONDS
        remaining_sec = max(0, end_ts - now)

        # 已耗时百分比 = (now - start) / total
        elapsed = max(0, now - start_ts)
        pct = min(elapsed / DISPATCH_TOTAL_SECONDS * 100, 100) if DISPATCH_TOTAL_SECONDS > 0 else 0

        if remaining_sec <= 0:
            status = "已完成"
            remain_h = 0
            remain_m = 0
        else:
            remain_h = remaining_sec // 3600
            remain_m = (remaining_sec % 3600) // 60
            if remain_h > 0:
                status = f"剩余 {remain_h}h{remain_m}m"
            else:
                status = f"剩余 {remain_m}m"

        # 显示用已耗时(spend_time 是 API 报告的整小时)
        spend_h = min(elapsed // 3600, 20)  # 不超过 20

        dispatch_list.append({
            "text": text,
            "reward_id": reward_id,
            "spend": spend_h,
            "total": 20,
            "remain_h": remain_h,
            "remain_m": remain_m,
            "status": status,
            "pct": round(pct, 1),
        })

    dispatch_count = len(dispatch_list)
    dispatch_status = f"{dispatch_count}/4 进行中" if dispatch_count > 0 else "空闲"

    # 数据时效提示
    data_time_str = ""
    if data_ts > 0:
        data_time_str = datetime.datetime.fromtimestamp(data_ts).strftime(
            "%m-%d %H:%M"
        )

    return {
        "nickname": role.get("nickname") or "搭配师",
        "level": role.get("level", 0),
        "avatar_path": avatar_path,
        "energy": estimated_energy,  # 卡片主显示用前端公式计算的当前体力
        "raw_energy": energy,  # API 返回的基线值(参考)
        "energy_max": ENERGY_MAX,
        "energy_pct": round(energy_pct, 1),
        "human_remaining": human_remaining,  # 距满血 "Xh Ym"
        "daily_task": daily_task,  # 已重置计算后的当前值
        "daily_task_max": daily_task_max,
        "daily_countdown": daily_countdown,  # "Xh Ym 后刷新"
        "daily_reset": daily_reset,  # 今天是否已过 04:00 重置点
        "task_status": task_done,
        "dispatch_count": dispatch_count,
        "dispatch_status": dispatch_status,
        "dispatch_list": dispatch_list,
        "star_sea": star_sea,
        "periodic_tower": periodic_tower,
        "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_time_str": data_time_str,
        "data_age_hours": round(data_age_h, 1),
    }


@sv_niki_stamina.on_command(("体力", "能量", "stamina", "energy", "tl"), block=True)
async def niki_stamina_cmd(bot: Bot, ev: Event):
    """nk体力 - 查询活跃能量、朝夕心愿、派遣等日常进度(图片)

    能量每 5 分钟恢复 1 点(前端公式实时计算),朝夕心愿每日 04:00 重置。
    每次都实时调 note/book/info + start_sync(需要游戏在线才会真正刷新)。
    token 过期(实时返回 None)时回退到缓存数据。
    """
    user = await NikiUser.get_active(ev.user_id, ev.bot_id)
    if user is None:
        accounts = await NikiUser.list_accounts(ev.user_id, ev.bot_id)
        await send_niki_notify(bot, ev, CommonMsg.not_logged_in(bool(accounts)))
        return

    # nickname/level 优先用数据库字段(刷新时会回写)
    cached_role: dict = {}

    # 1. 实时请求最新体力数据(会先调 start_sync 触发游戏上传,需要游戏在线)
    realtime = await fetch_realtime_stamina(
        token=user.token,
        openid=user.openid,
        client_id=user.client_id,
    )

    # 2. 实时失败时回退到缓存(token 过期会返回 None)
    if realtime is not None:
        user_data = realtime
        data_source = "实时"
    else:
        logger.warning(f"[niki体力] 实时获取失败,回退缓存 user_id={ev.user_id}")
        cached = await load_cached_data(USER_DATA_PATH, user.openid, logger)
        if not cached:
            await send_niki_notify(bot, ev, CommonMsg.not_logged_in(True))
            return
        journal_data = cached.get("journal_data", {})
        state = journal_data.get("state", {})
        user_data = state.get("userData", {})
        cached_role = cached.get("login_info", {}).get("user_info", {}).get("role", {})
        data_source = "缓存"

    # 3. 实时成功时也要取一次缓存(头像/nickname 在缓存里,实时接口不返回)
    if realtime is not None:
        cached = await load_cached_data(USER_DATA_PATH, user.openid, logger)
        if cached:
            cached_role = cached.get("login_info", {}).get("user_info", {}).get("role", {})

    role = {
        "nickname": user.nickname or cached_role.get("nickname") or "搭配师",
        "level": user.level or cached_role.get("level", 0),
        "avatar": cached_role.get("avatar", ""),
    }

    logger.info(
        f"[niki体力] 渲染 user_id={ev.user_id} 来源={data_source} "
        f"energy={user_data.get('energy')}"
    )

    try:
        # 头像路径
        uid = user.uid or user.openid
        user_dir = USER_DATA_PATH / uid
        avatar_path = ""
        avatar_file = user_dir / "avatar.png"
        if avatar_file.exists():
            avatar_path = f"file:///{str(avatar_file.resolve()).replace(chr(92), '/')}"
        elif role.get("avatar"):
            avatar_path = role.get("avatar")

        ctx = _build_stamina_context(user_data, role, avatar_path)
        # 在卡片标题旁标注数据来源(实时/缓存)
        ctx["data_source"] = data_source

        html = NIKI_TEMPLATES.get_template("stamina.html").render(**ctx)
        img = await render_html_to_image(
            html, user_data_dir=user_dir, max_width=760.0
        )

        if img:
            await bot.send(MessageSegment.image(img))
        else:
            await send_niki_notify(bot, ev, "体力卡片渲染失败,请稍后再试")
    except Exception as e:
        logger.exception(f"[niki体力] 渲染失败: {e}")
        await send_niki_notify(bot, ev, "体力查询失败,请稍后再试")
