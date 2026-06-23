"""NIKIUID 消息文案常量。

参考 NTEUID/utils/msgs/__init__.py 的模式,集中管理给用户看的文案,
方便统一修改和多前缀适配。
"""

from __future__ import annotations

from ..niki_config.prefix import niki_prefix

TITLE = "[无限暖暖]\n"


class CommonMsg:
    NOT_LOGGED_IN = "尚未登录无限暖暖账号"
    RETRY_LATER = "服务暂时不可用，请稍后再试"

    @classmethod
    def not_logged_in(cls, has_history: bool = False) -> str:
        if has_history:
            return cls.login_expired()
        return f"{cls.NOT_LOGGED_IN}，请先发送【{niki_prefix()}登录】"

    @classmethod
    def login_expired(cls) -> str:
        return f"登录已失效，请重新发送【{niki_prefix()}登录】"


class LoginMsg:
    USER_CENTER_LOGIN_FAILED = "登录失败，请稍后再试"
    SUCCESS = "登录成功"
    LINK_COPY = "请复制地址到浏览器打开"
    MOBILE_INVALID = "手机号格式错误"
    CODE_INVALID = "验证码格式错误"
    SMS_SENT = "验证码已发送"
    SMS_SEND_FAILED = "验证码发送失败，请稍后再试"
    SMS_VERIFIED = "短信验证通过，请回到对话查看登录结果"
    SMS_LOGIN_FAILED = "验证码错误或已过期，请重新获取"
    NOT_LOGGED_IN = "你还没有登录无限暖暖账号"
    LOGOUT_DONE = "已退出登录，当前账号已删除"
    LOGOUT_ALL_DONE = "已退出登录，所有账号已删除"
    REFRESH_NO_ACCOUNT = "你还没有登录无限暖暖账号"

    @classmethod
    def link_ttl(cls) -> str:
        from ..niki_config.niki_config import NikiConfig

        ttl_s = NikiConfig.get_config("NikiLoginTTL").data
        if ttl_s >= 60 and ttl_s % 60 == 0:
            return f"登录地址{ttl_s // 60}分钟内有效"
        return f"登录地址{ttl_s}秒内有效"

    @classmethod
    def timeout(cls) -> str:
        return f"登录超时，请重新发送【{niki_prefix()}登录】"

    @classmethod
    def session_expired(cls) -> str:
        return f"登录会话已失效，请重新发送【{niki_prefix()}登录】"

    @classmethod
    def link_expired(cls) -> str:
        return f"链接已失效，请回到对话重新发送 {niki_prefix()}登录"


class CardMsg:
    LOAD_FAILED = "卡片生成失败，请稍后再试"
    EMPTY = "暂无可展示的数据"
    REFRESHING = "正在生成卡片，请稍候..."


class RefreshMsg:
    FAILED = "刷新失败，token 可能已过期，请重新登录"
    REFRESHING = "正在刷新数据，请稍候..."

    @classmethod
    def success(cls, nickname: str, level: int) -> str:
        return f"数据刷新成功！\n搭配师: {nickname}\n等级: {level}"


async def send_niki_notify(
    bot,
    ev,
    msg: str,
    need_at: bool = True,
) -> None:
    """统一发送带 [无限暖暖] 标题的消息。"""
    at_sender = need_at and bool(ev.group_id)
    await bot.send(f"{TITLE}{msg}", at_sender=at_sender)
