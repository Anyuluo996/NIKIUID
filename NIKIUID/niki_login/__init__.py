"""NIKIUID 登录子模块。

注册「niki登录」「niki退出登录」等命令,并通过副作用 import 让
login_router 里的 FastAPI 路由在模块加载时自动注册。
"""

from __future__ import annotations

import re

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from . import login_router  # 纯副作用 import:FastAPI 路由在模块加载时注册
from .login_service import logout, logout_all, request_login, login_by_password

_ = login_router  # 防 linter 误删

sv_niki_login = SV("niki登录")


@sv_niki_login.on_command(("登录", "登陆", "login", "dl"))
async def niki_login_cmd(bot: Bot, ev: Event):
    """niki登录 - 获取网页登录链接

    带参数时走账号密码直登:niki登录 手机号,密码(仅限私聊)
    无参数则获取一次性网页登录链接(短信验证,群聊/私聊均可)
    """
    text = re.sub(r'["\n\t ]+', "", ev.text.strip())
    if text == "":
        return await request_login(bot, ev)

    # 带参数:账号密码登录(支持 逗号/空格 分隔)
    # 账号密码包含敏感信息,仅限私聊使用,群聊拒绝
    if ev.group_id:
        await bot.send(
            "[无限暖暖]\n账号密码登录涉及敏感信息,请私聊机器人使用\n"
            "或发送「niki登录」获取网页链接登录(支持群聊)",
            at_sender=True,
        )
        return

    parts = re.split(r"[,\s]+", text)
    if len(parts) < 2 or not parts[0] or not parts[1]:
        await bot.send(
            "[无限暖暖]\n账号密码登录格式:niki登录 手机号,密码\n无参数则获取网页登录链接",
            at_sender=bool(ev.group_id),
        )
        return

    account, password = parts[0], parts[1]
    await login_by_password(bot, ev, account, password)


@sv_niki_login.on_fullmatch(("退出登录", "退出登陆", "登出", "logout", "tcdl", "dc"))
async def niki_logout_cmd(bot: Bot, ev: Event):
    """niki退出登录 / nk登出 - 删除当前账号"""
    await logout(bot, ev)


@sv_niki_login.on_fullmatch(("全部登出", "退出全部登录", "退出全部登陆", "qbdc", "qbzc"))
async def niki_logout_all_cmd(bot: Bot, ev: Event):
    """全部登出 - 删除所有账号"""
    await logout_all(bot, ev)
