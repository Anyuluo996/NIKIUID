"""体力计算回归测试 — 防止之前的 energy=6 / 朝夕心愿 / dispatch bug 复现。"""

from gsuid_core.plugins.NIKIUID.NIKIUID.utils.services.stamina_service import (
    ENERGY_MAX,
    ENERGY_REGEN_SECONDS_PER_POINT,
    DAILY_TASK_MAX,
    _calc_daily_task,
    _human_countdown,
    _calc_estimated_energy,
)
from gsuid_core.plugins.NIKIUID.NIKIUID.niki_stamina import _format_dispatch

from .conftest import (
    DOC_ENERGY,
    DOC_TIMESTAMP,
    DOC_NOW,
    DOC_EXPECTED_CURRENT,
)


class TestCalcEstimatedEnergy:
    """能量回复公式: min(energy + (now-ts)//300, 350)"""

    def test_documented_case(self):
        """文档实测用例: energy=6, ts=1782091216, now=1782170450 → 270"""
        r = _calc_estimated_energy(DOC_ENERGY, DOC_TIMESTAMP, DOC_NOW)
        assert r["current"] == DOC_EXPECTED_CURRENT

    def test_no_regen_when_just_synced(self):
        """刚同步(数据时间=当前时间),recovered 应为 0"""
        now = 1782170450
        r = _calc_estimated_energy(100, now, now)
        assert r["current"] == 100
        assert r["recovered"] == 0

    def test_regen_one_point_after_5min(self):
        """5 分钟后回复 1 点"""
        now = 1782170450
        r = _calc_estimated_energy(100, now - 300, now)
        assert r["current"] == 101
        assert r["recovered"] == 1

    def test_cap_at_max(self):
        """回复不超过 350"""
        now = 1782170450
        r = _calc_estimated_energy(340, now - 3600, now)  # 1 小时 = 12 点
        assert r["current"] == ENERGY_MAX  # 350
        assert r["remaining_points"] == 0
        assert r["human_remaining"] == "已满"

    def test_full_to_empty(self):
        """0 能量 + 长时间 → 接近满值"""
        now = 1782170450
        # 350 点 * 300 秒 = 105000 秒 ≈ 29.2 小时
        r = _calc_estimated_energy(0, now - 105000, now)
        assert r["current"] == 350
        assert r["human_remaining"] == "已满"

    def test_human_remaining_format(self):
        """距满血时间格式 'Xh Ym'"""
        now = 1782170450
        r = _calc_estimated_energy(348, now, now)  # 还差 2 点 = 10 分钟
        assert r["human_remaining"] == "0h10m"

    def test_negative_timestamp_fallback(self):
        """timestamp 为 0 或负数时退化为 now(recovered=0)"""
        now = 1782170450
        r = _calc_estimated_energy(50, 0, now)
        assert r["current"] == 50
        assert r["recovered"] == 0


class TestCalcDailyTask:
    """朝夕心愿: 每日 04:00(北京时间)重置"""

    def test_reset_after_4am(self):
        """今天已过 04:00,但数据同步在今天 04:00 之前 → 重置为 0"""
        # 2026-06-23 07:30 北京时间
        now = DOC_NOW
        # 2026-06-22 09:20(昨天同步)
        data_ts = DOC_TIMESTAMP
        r = _calc_daily_task(500, data_ts, now)
        assert r["current"] == 0
        assert r["reset"] is True

    def test_no_reset_same_day_after_4am(self):
        """今天 04:00 之后同步 → 不重置"""
        now = DOC_NOW
        # 今天 05:00 同步(在 04:00 之后)
        data_ts = now - 2 * 3600  # 2 小时前
        r = _calc_daily_task(300, data_ts, now)
        assert r["current"] == 300
        assert r["reset"] is False

    def test_no_reset_before_4am(self):
        """今天还没到 04:00 → 不重置"""
        # 构造一个北京时间凌晨 02:00 的时间戳
        # 2026-06-23 02:00 北京 = 2026-06-22 18:00 UTC
        # 取一个确定值: now=1782156000(约 2026-06-23 02:00 北京)
        now = 1782156000
        data_ts = now - 3600  # 1 小时前同步
        r = _calc_daily_task(200, data_ts, now)
        assert r["current"] == 200
        assert r["reset"] is False

    def test_reset_at_ts_is_tomorrow_4am(self):
        """reset_at_ts 应该是明天 04:00(今天已过 04:00)"""
        now = DOC_NOW
        r = _calc_daily_task(500, DOC_TIMESTAMP, now)
        # reset_at_ts 应该在 now 之后(明天 04:00)
        assert r["reset_at_ts"] > now


class TestHumanCountdown:
    """倒计时格式化"""

    def test_days_hours(self):
        assert _human_countdown(1782170450 + 86400 + 3600, 1782170450) == "1d1h"

    def test_hours_minutes(self):
        assert _human_countdown(1782170450 + 7200 + 300, 1782170450) == "2h5m"

    def test_minutes_only(self):
        assert _human_countdown(1782170450 + 300, 1782170450) == "5m"

    def test_already_past(self):
        assert _human_countdown(1782170450 - 100, 1782170450) == "已刷新"

    def test_zero_diff(self):
        assert _human_countdown(1782170450, 1782170450) == "已刷新"


class TestFormatDispatch:
    """派遣任务格式化"""

    def test_completed_dispatch(self, sample_dispatch):
        """所有派遣任务都已超 20 小时 → 全部已完成"""
        now = sample_dispatch[0]["start_time"] + 25 * 3600  # 25 小时后
        result = _format_dispatch(sample_dispatch, now)
        assert len(result) == 4
        for item in result:
            assert item["status"] == "已完成"
            assert item["pct"] == 100.0

    def test_in_progress_dispatch(self, sample_dispatch):
        """派遣任务进行中(过了 10 小时)→ 剩余 10 小时"""
        now = sample_dispatch[0]["start_time"] + 10 * 3600
        result = _format_dispatch(sample_dispatch, now)
        assert result[0]["status"] == "剩余 10h0m"
        assert 49 < result[0]["pct"] < 51  # ~50%

    def test_just_started(self, sample_dispatch):
        """刚开始的派遣 → 剩余接近 20 小时"""
        now = sample_dispatch[0]["start_time"] + 60  # 1 分钟后
        result = _format_dispatch(sample_dispatch, now)
        assert "19h" in result[0]["status"]
        assert result[0]["pct"] < 1

    def test_empty_dispatch(self):
        """空列表 → 空结果"""
        assert _format_dispatch([], 1782170450) == []

    def test_non_dict_entries_skipped(self):
        """非 dict 元素被跳过"""
        result = _format_dispatch(["bad", None, 123], 1782170450)
        assert result == []

    def test_missing_start_time(self):
        """start_time 缺失 → 按 0 处理"""
        result = _format_dispatch([{"text": "test"}], 1782170450)
        assert len(result) == 1
        assert result[0]["status"] == "已完成"  # 0 + 20h 很久以前
