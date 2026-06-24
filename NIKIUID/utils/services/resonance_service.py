"""共鸣数据服务"""

import json

import aiohttp

from gsuid_core.logger import logger

from ..constants import CLIENT_ID, MYL_API_BASE

# logger 由 gsuid_core.logger 提供


async def fetch_resonance_with_api(
    token: str, openid: str, client_id: int | None = None
) -> dict | None:
    """使用 API 获取共鸣数据（快速模式）

    Args:
        token: 登录 token
        openid: 用户 openid
        client_id: 客户端ID

    Returns:
        包含 suitCardListData 的字典（含共鸣抽数，含进化套装贡献）
    """
    cid = client_id or CLIENT_ID
    base_params = {
        "client_id": cid,
        "token": token,
        "openid": openid,
    }

    raw_suit_list: list[dict] = []
    owned_suit_ids: set[str] = set()

    try:
        from ..auth.passport import myl_sign_params

        async with aiohttp.ClientSession() as session:
            # suit/list - 获取套装基本信息
            suit_api_url = f"{MYL_API_BASE}/v1/strategy/main/suit/list"
            suit_data = myl_sign_params(base_params.copy())
            async with session.post(
                suit_api_url,
                json=suit_data,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    suit_result = await resp.json()
                    if suit_result.get("code") == 0:
                        raw_suit_list = suit_result.get("data", {}).get("list", [])

            # note/book/info (snappy 压缩) - 获取已共鸣套装 + 共鸣抽数
            note_api_url = f"{MYL_API_BASE}/v1/strategy/user/note/book/info"
            note_data = myl_sign_params(base_params.copy())
            note_decompressed: dict | None = None
            async with session.post(
                note_api_url,
                json=note_data,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    note_raw = await resp.read()
                    try:
                        from .draw_num_service import (
                            decompress_snappy_payload,
                        )

                        decompressed = decompress_snappy_payload(note_raw)
                        note_decompressed = json.loads(decompressed.decode("utf-8"))
                        iself = note_decompressed.get("info_from_self", {})
                        owned_suit_ids = {
                            str(sid) for sid in iself.get("suit_list", [])
                        }
                    except ImportError:
                        logger.error("snappy 未安装，无法解压 note/book/info 数据，请运行: pip install python-snappy")
                    except Exception as e:
                        logger.error(f"解压 note/book/info 失败: {e}", exc_info=True)
                else:
                    logger.warning(f"note/book/info API 返回非 200 状态: {resp.status}")

        # 计算共鸣抽数（含进化套装贡献），复用 note_decompressed 避免重复解压
        if note_decompressed:
            try:
                from .draw_num_service import (
                    merge_draw_info_to_suit_card_list,
                    parse_note_book_info_with_suit_list,
                )

                logger.info(f"开始计算共鸣抽数，note_decompressed keys: {list(note_decompressed.keys())[:10]}")
                logger.info(f"raw_suit_list length: {len(raw_suit_list)}")

                draw_info_map = parse_note_book_info_with_suit_list(
                    note_decompressed, raw_suit_list
                )
                if draw_info_map:
                    raw_suit_list = merge_draw_info_to_suit_card_list(
                        raw_suit_list, draw_info_map
                    )
                    logger.info(f"共鸣抽数计算完成，覆盖 {len(draw_info_map)} 个套装")
                else:
                    logger.warning("共鸣抽数计算返回空结果，返回原始数据")
            except ImportError as e:
                logger.error(f"导入抽卡计算模块失败: {e}，请安装python-snappy: pip install python-snappy")
            except Exception as e:
                logger.exception(f"共鸣抽数计算异常: {e}，请检查python-snappy是否正确安装")

        # 提取完整用户统计(info_from_gm 含 45 字段 + info_from_self 含 5 字段)
        # 参考 docs/API_USAGE.md 第 3.2 节
        user_self_stats: dict = {}
        if note_decompressed:
            iself = note_decompressed.get("info_from_self", {})
            igm = note_decompressed.get("info_from_gm", {})

            # info_from_self 的 5 个字段(login_days, total_play_time, gacha_list, suit_list, box_count)
            user_self_stats["login_days"] = iself.get("login_days", 0)
            user_self_stats["total_play_time"] = iself.get("total_play_time", 0)

            # info_from_gm 的 45 个字段(完整 userData)
            # 基础信息
            user_self_stats["cloth_num"] = igm.get("cloth_num", 0)
            user_self_stats["momo_num"] = igm.get("momo_num", 0)
            user_self_stats["designdrawing_num"] = igm.get("designdrawing_num", 0)
            user_self_stats["box_num"] = igm.get("box_num", 0)
            user_self_stats["achievement_num"] = igm.get("achievement_num", 0)
            user_self_stats["energy"] = igm.get("energy", 0)
            user_self_stats["daily_task"] = igm.get("daily_task", 0)
            # 共鸣抽数
            user_self_stats["draw_num"] = igm.get("draw_num", 0)
            user_self_stats["periodic_draw_num"] = igm.get("periodic_draw_num", 0)
            user_self_stats["permanent_draw_num"] = igm.get("permanent_draw_num", 0)
            # 心愿原野
            user_self_stats["whimsystar_num"] = igm.get("whimsystar_num", 0)
            user_self_stats["dew_num"] = igm.get("dew_num", 0)
            user_self_stats["pillar_num"] = igm.get("pillar_num", 0)
            user_self_stats["permanent_tower"] = igm.get("permanent_tower", 0)
            user_self_stats["star_sea"] = igm.get("star_sea", 0)
            # 伊赞之土/万相境
            user_self_stats["imagine_lantern_num"] = igm.get("imagine_lantern_num", 0)
            user_self_stats["imagine_bell_num"] = igm.get("imagine_bell_num", 0)
            # 花焰群岛
            user_self_stats["imagine_ballon_num"] = igm.get("imagine_ballon_num", 0)
            user_self_stats["flame_light_stone_num"] = igm.get("flame_light_stone_num", 0)
            # 无忧岛
            user_self_stats["imagine_foam_num"] = igm.get("imagine_foam_num", 0)
            user_self_stats["worry_free_beads_num"] = igm.get("worry_free_beads_num", 0)
            # 丹青屿
            user_self_stats["imagine_jade_num"] = igm.get("imagine_jade_num", 0)
            user_self_stats["danqing_jade_num"] = igm.get("danqing_jade_num", 0)
            # 其它
            user_self_stats["periodic_tower"] = igm.get("periodic_tower", 0)
            user_self_stats["reading_exploration"] = igm.get("reading_exploration", 0)
            user_self_stats["creature_explore_num"] = igm.get("creature_explore_num", 0)
            user_self_stats["title_str"] = igm.get("title_str", "")
            # 列表/字典字段(原样传递,供体力/派遣等功能使用)
            user_self_stats["dispatch"] = igm.get("dispatch", [])
            user_self_stats["currency_count"] = igm.get("currency_count", [])
            user_self_stats["clothes"] = igm.get("clothes", [])
            user_self_stats["suits"] = igm.get("suits", [])
            user_self_stats["most_collected_plant"] = igm.get("most_collected_plant", {})
            user_self_stats["most_cleaned_animal"] = igm.get("most_cleaned_animal", {})
            user_self_stats["most_collected_insect"] = igm.get("most_collected_insect", {})
            user_self_stats["most_purified_monster"] = igm.get("most_purified_monster", {})
            user_self_stats["most_caught_fish"] = igm.get("most_caught_fish", {})
            user_self_stats["heaviest_caught_fish"] = igm.get("heaviest_caught_fish", {})
            user_self_stats["weekly_refresh_time"] = igm.get("weekly_refresh_time", 0)
            user_self_stats["weekly_reward_status"] = igm.get("weekly_reward_status", 0)
            user_self_stats["daily_refresh_time"] = igm.get("daily_refresh_time", 0)
            # 货币分项(伊赞/心愿的奇想星和灵感露珠)
            for c in igm.get("currency_count", []):
                if isinstance(c, dict):
                    iid = c.get("item_id")
                    if iid is not None:
                        user_self_stats[f"currency_{iid}"] = c.get("count", 0)

        logger.info(
            f"从 API 获取到 {len(raw_suit_list)} 个套装，{len(owned_suit_ids)} 个已共鸣，"
            f"用户统计: login_days={user_self_stats.get('login_days', 0)}, "
            f"draw_num={user_self_stats.get('draw_num', 0)}"
        )
        return {
            "suitCardListData": raw_suit_list,
            "ownedSuitIds": list(owned_suit_ids),
            "userSelfStats": user_self_stats,
        }

    except Exception as e:
        logger.warning(f"API 获取共鸣数据失败: {e}")
        return {"suitCardListData": [], "ownedSuitIds": [], "userSelfStats": {}}
