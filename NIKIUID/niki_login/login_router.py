"""登录页 FastAPI 路由。

参考 NTEUID/nte_login/login_router.py,在 gsuid_core 全局 app 上注册路由。
模块被 import 时(由 niki_login/__init__.py 的副作用 import 触发),
装饰器执行,路由自动注册。
"""

from __future__ import annotations

import re
from dataclasses import asdict

from fastapi import Request
from pydantic import BaseModel
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from gsuid_core.logger import logger
from gsuid_core.web_app import app

from ..utils.msgs import LoginMsg
from ..utils.resource.RESOURCE_PATH import NIKI_TEMPLATES
from .login_service import LOGIN_CACHE, LoginResult, LoginState, perform_login, send_login_sms

_MOBILE_RE = re.compile(r"^1\d{10}$")
_CODE_RE = re.compile(r"^\d{4,8}$")


def _json(result: LoginResult) -> JSONResponse:
    return JSONResponse(asdict(result), status_code=200 if result.ok else 400)


def _login_user_id(auth_token: str) -> str:
    state: LoginState | None = LOGIN_CACHE.get(auth_token)
    return state.user_id if state else "unknown"


class _SendSmsPayload(BaseModel):
    auth: str
    mobile: str


class _LoginPayload(BaseModel):
    auth: str
    mobile: str
    code: str


@app.get("/niki/i/{auth_token}")
async def niki_login_page(auth_token: str) -> HTMLResponse:
    """登录页:校验 auth token 有效后渲染 login.html。"""
    state: LoginState | None = LOGIN_CACHE.get(auth_token)
    if not state:
        return HTMLResponse(LoginMsg.link_expired(), status_code=404)
    if state.ok:
        return RedirectResponse("/niki/done", status_code=303)
    return HTMLResponse(
        NIKI_TEMPLATES.get_template("login.html").render(
            auth=auth_token,
            user_id=state.user_id,
            msg={
                "smsSent": LoginMsg.SMS_SENT,
                "smsSendFailed": LoginMsg.SMS_SEND_FAILED,
                "loginSuccess": LoginMsg.SMS_VERIFIED,
                "loginFailed": LoginMsg.USER_CENTER_LOGIN_FAILED,
            },
        )
    )


@app.get("/niki/done")
async def niki_login_done() -> HTMLResponse:
    """登录完成页(纯静态)。"""
    return HTMLResponse(NIKI_TEMPLATES.get_template("done.html").render())


@app.post("/niki/sendSmsCode")
async def niki_send_sms(payload: _SendSmsPayload, _request: Request) -> JSONResponse:
    """网页侧:发送短信验证码。"""
    if not _MOBILE_RE.match(payload.mobile):
        return _json(LoginResult.fail(LoginMsg.MOBILE_INVALID))

    try:
        return _json(await send_login_sms(payload.auth, payload.mobile))
    except Exception as error:
        logger.warning(
            f"[niki登录] 短信下发失败 user_id={_login_user_id(payload.auth)}: {error!r}"
        )
        return _json(LoginResult.fail(LoginMsg.SMS_SEND_FAILED))


@app.post("/niki/login")
async def niki_perform_login(payload: _LoginPayload, _request: Request) -> JSONResponse:
    """网页侧:提交验证码完成登录。"""
    if not _MOBILE_RE.match(payload.mobile):
        return _json(LoginResult.fail(LoginMsg.MOBILE_INVALID))
    if not _CODE_RE.match(payload.code):
        return _json(LoginResult.fail(LoginMsg.CODE_INVALID))

    try:
        return _json(await perform_login(payload.auth, payload.mobile, payload.code))
    except Exception as error:
        logger.warning(
            f"[niki登录] 登录失败 user_id={_login_user_id(payload.auth)}: {error!r}"
        )
        return _json(LoginResult.fail(LoginMsg.SMS_LOGIN_FAILED))


@app.get("/niki/status/{auth_token}")
async def niki_login_status(auth_token: str) -> JSONResponse:
    """查询登录状态(给轮询用)。"""
    state: LoginState | None = LOGIN_CACHE.get(auth_token)
    if not state:
        return JSONResponse({"status": "expired"})
    return JSONResponse(
        {
            "status": state.status,
            "ok": state.ok,
            "msg": state.msg,
        }
    )
