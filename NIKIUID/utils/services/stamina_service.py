"""体力实时数据服务

注意: note/book/info 的 info_from_gm 是「游戏客户端推送缓存」,
energy / dispatch 等字段反映的是上次游戏端上传时的状态(有 timestamp),
不是真正的服务器实时值。能量回复速度由客户端驱动,服务器不自动累加。

因此本服务:
1. 先调 post/start_sync 触发游戏客户端上传最新数据(需要游戏在线)
2. 然后调 note/book/info 拿数据
3. 返回数据时附带 timestamp,让卡片能标注「数据来自 X 小时前」

失败时返回 None,调用方回退到缓存数据。
"""

from __future__ import annotations

import datetime
import json
import time

import aiohttp

from gsuid_core.logger import logger

from ..auth.passport import myl_sign_params
from ..constants import CLIENT_ID, MYL_API_BASE
from .draw_num_service import decompress_snappy_payload

# 能量上限(SPA 硬编码,详见 docs/DATA_FIELDS.md §5.X)
ENERGY_MAX = 350
# 能量回复速率:5 分钟 = 300 秒 / 点(实测推导,文档 §5.X.3 React 源码确认)
ENERGY_REGEN_SECONDS_PER_POINT = 300
# 朝夕心愿每日上限(SPA 硬编码,文档 §5.Y.2)
DAILY_TASK_MAX = 500
# 时区:北京时间(文档 §5.Y.1 重置时间硬编码为 Asia/Shanghai 04:00)
TZ_SHANGHAI = datetime.timezone(datetime.timedelta(hours=8))


def _calc_daily_task(api_value: int, data_ts: int, now_ts: int) -> dict:
    """朝夕心愿:每日 04:00(北京时间)重置显示。

    公式(文档 §5.Y.1):
        若 上次同步 < 今日4点 且 当前时间 ≥ 今日4点 → 显示 0
        否则显示 API 原值(周累计)

    Args:
        api_value: userData.daily_task(API 返回的周累计)
        data_ts: userData.timestamp(上次同步秒级时间戳)
        now_ts: 当前时间戳(秒)

    Returns:
        {current, max, reset, reset_at_ts}
    """
    now_dt = datetime.datetime.fromtimestamp(now_ts, tz=TZ_SHANGHAI)
    today_4am = now_dt.replace(
        hour=4, minute=0, second=0, microsecond=0
    )
    today_4am_ts = int(today_4am.timestamp())

    reset = data_ts < today_4am_ts and now_ts >= today_4am_ts
    current = 0 if reset else api_value
    # 下次刷新时间:今天已过 4 点则明天 4 点,否则今天 4 点
    next_reset = today_4am_ts + 86400 if now_ts >= today_4am_ts else today_4am_ts
    return {
        "current": current,
        "max": DAILY_TASK_MAX,
        "reset": reset,
        "reset_at_ts": next_reset,
    }


def _human_countdown(target_ts: int, now_ts: int) -> str:
    """把目标时间戳格式化成距现在的可读倒计时 "Xh Ym" / "Xd Yh"。"""
    diff = target_ts - now_ts
    if diff <= 0:
        return "已刷新"
    days = diff // 86400
    hours = (diff % 86400) // 3600
    minutes = (diff % 3600) // 60
    if days > 0:
        return f"{days}d{hours}h"
    if hours > 0:
        return f"{hours}h{minutes}m"
    return f"{minutes}m"


async def _trigger_start_sync(
    session: aiohttp.ClientSession,
    token: str,
    openid: str,
    cid: int,
) -> bool:
    """触发游戏客户端上传最新数据。需要游戏在线才会真正上传。

    Returns:
        True 表示 API 接受请求(不代表游戏已上传,上传有 5-10 分钟延迟)
    """
    try:
        async with session.post(
            f"{MYL_API_BASE}/v1/strategy/post/start_sync",
            json=myl_sign_params(
                {"client_id": cid, "token": token, "openid": openid}
            ),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                logger.warning(f"[niki体力] start_sync 返回状态 {resp.status}")
                return False
            data = await resp.json()
            ok = data.get("code") == 0
            logger.info(f"[niki体力] start_sync code={data.get('code')} ok={ok}")
            return ok
    except Exception as e:
        logger.warning(f"[niki体力] start_sync 异常: {e}")
        return False


async def fetch_realtime_stamina(
    token: str,
    openid: str,
    client_id: int | None = None,
) -> dict | None:
    """获取最新体力相关数据。

    流程: 先 start_sync 触发上传 → 拉取 note/book/info。
    返回字段含 data_timestamp(数据采集时刻)和 estimated_energy(估算回复后能量)。

    Args:
        token: 登录 token
        openid: 用户 openid
        client_id: 客户端 ID

    Returns:
        包含 energy / daily_task / dispatch / star_sea / periodic_tower
        / data_timestamp / estimated_energy 的字典;
        token 过期或网络异常返回 None。
    """
    cid = client_id or CLIENT_ID
    if not token or not openid:
        logger.warning("[niki体力] 实时查询: token 或 openid 为空")
        return None

    base_params = {"client_id": cid, "token": token, "openid": openid}
    now = int(time.time())

    try:
        async with aiohttp.ClientSession() as session:
            # 1. 触发游戏客户端上传最新数据(需要游戏在线)
            await _trigger_start_sync(session, token, openid, cid)

            # 2. 拉取 note/book/info
            url = f"{MYL_API_BASE}/v1/strategy/user/note/book/info"
            payload = myl_sign_params(base_params.copy())
            async with session.post(
                url,
                json=payload,
                headers={"referer": "https://myl.nuanpaper.com/"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"[niki体力] note/book/info 返回状态 {resp.status}"
                    )
                    return None
                raw = await resp.read()

        # 解压 snappy
        try:
            decompressed = decompress_snappy_payload(raw)
            data = json.loads(decompressed.decode("utf-8"))
        except ImportError:
            logger.error(
                "[niki体力] snappy 未安装,请运行 pip install python-snappy"
            )
            return None
        except Exception as e:
            logger.error(f"[niki体力] 实时查询解压失败: {e}")
            return None

        # code 校验(token 过期会返回非 0 code)
        code = data.get("code")
        if code not in (0, None):
            logger.warning(
                f"[niki体力] note/book/info code={code} info={data.get('info', '')}"
            )
            return None

        igm = data.get("info_from_gm", {})
        if not igm:
            logger.warning("[niki体力] info_from_gm 为空")
            return None

        energy = int(igm.get("energy", 0) or 0)
        data_ts = int(igm.get("timestamp", 0) or 0)
        # timestamp 缺失时退化为 now(避免 elapsed 为负导致回血为负)
        if data_ts <= 0:
            data_ts = now

        # 体力计算公式(与 SPA 前端完全一致,详见 docs/DATA_FIELDS.md §5.X):
        #   current = min(energy + floor((now - timestamp) / 300), 350)
        elapsed = max(0, now - data_ts)
        recovered = elapsed // ENERGY_REGEN_SECONDS_PER_POINT
        current = min(energy + recovered, ENERGY_MAX)
        remaining_points = ENERGY_MAX - current
        seconds_to_full = remaining_points * ENERGY_REGEN_SECONDS_PER_POINT
        # 距满血的可读时长 "Xh Ym"
        full_min = remaining_points * (ENERGY_REGEN_SECONDS_PER_POINT // 60)
        human_remaining = (
            f"{full_min // 60}h{full_min % 60}m" if remaining_points > 0 else "已满"
        )

        # 朝夕心愿:每日 04:00 重置显示(文档 §5.Y)
        daily_api = int(igm.get("daily_task", 0) or 0)
        daily = _calc_daily_task(daily_api, data_ts, now)
        daily_countdown = _human_countdown(daily["reset_at_ts"], now)

        result = {
            "energy": energy,  # 原始基线值(非当前体力)
            "energy_max": ENERGY_MAX,
            "estimated_energy": current,  # 当前体力(前端公式计算)
            "recovered_points": recovered,
            "remaining_points": remaining_points,
            "seconds_to_full": seconds_to_full,
            "human_remaining": human_remaining,
            "data_timestamp": data_ts,
            "data_age_hours": (now - data_ts) / 3600,
            "daily_task": daily["current"],  # 重置后的当前值
            "daily_task_raw": daily_api,  # API 原值(周累计,参考)
            "daily_task_max": DAILY_TASK_MAX,
            "daily_reset": daily["reset"],  # 今天是否已重置
            "daily_countdown": daily_countdown,  # "Xh Ym 后刷新"
            "star_sea": int(igm.get("star_sea", 0) or 0),
            "periodic_tower": int(igm.get("periodic_tower", 0) or 0),
            "dispatch": igm.get("dispatch", []),
        }
        logger.info(
            f"[niki体力] 实时查询成功 baseline_energy={energy} "
            f"current={current}/{ENERGY_MAX} recovered=+{recovered} "
            f"data_age={result['data_age_hours']:.1f}h "
            f"距满={human_remaining} "
            f"daily_task={daily['current']}/{DAILY_TASK_MAX}"
            f"{'(已重置)' if daily['reset'] else ''} "
            f"dispatch={len(result['dispatch'])}个"
        )
        return result
    except aiohttp.ClientError as e:
        logger.warning(f"[niki体力] 实时查询网络异常: {e}")
        return None
    except Exception as e:
        logger.exception(f"[niki体力] 实时查询未知异常: {e}")
        return None
