"""Passport API 认证"""

from __future__ import annotations

import hmac
import json
import time
import hashlib
from typing import Any

import aiohttp

from gsuid_core.logger import logger

from .crypto import (
    aes_decrypt,
    aes_encrypt,
    generate_doid,
    generate_device_id,
    generate_web_deviceid,
)
from ..constants import (
    CLIENT_ID,
    PASSPORT_APP_ID,
    PASSPORT_AES_KEY,
    PASSPORT_APP_KEY,
    PASSPORT_API_BASE,
)


def _mask_text(value: str, keep: int = 4) -> str:
    """Mask sensitive text for logs."""
    if not value:
        return "***"
    if len(value) <= keep:
        return "*" * len(value)
    return f"{value[:keep]}***"


def _mask_phone(phone: str) -> str:
    """手机号脱敏:保留前 3 后 4,中间打码。"""
    if not phone or len(phone) < 7:
        return _mask_text(phone or "")
    return f"{phone[:3]}****{phone[-4:]}"


def _build_sms_sign(timestamp: str) -> str:
    """Build the HMAC-MD5 signature for SMS endpoints."""
    sign_str = (
        f"app_id={PASSPORT_APP_ID}&clientid={CLIENT_ID}&lang=zh-cn"
        f"&sign_type=hmac&timestamp={timestamp}"
    )
    return hmac.new(
        PASSPORT_APP_KEY.encode(),
        sign_str.encode(),
        hashlib.md5,
    ).hexdigest()


def _build_sms_form(encrypted: str, timestamp: str) -> aiohttp.FormData:
    """Build the form body for SMS endpoints."""
    form = aiohttp.FormData()
    form.add_field("app_id", str(PASSPORT_APP_ID))
    form.add_field("clientid", str(CLIENT_ID))
    form.add_field("lang", "zh-cn")
    form.add_field("sign_type", "hmac")
    form.add_field("timestamp", timestamp)
    form.add_field("data", encrypted)
    form.add_field("sign", _build_sms_sign(timestamp))
    return form


def sign_params(params: dict[str, Any]) -> dict[str, Any]:
    """为 Passport API 参数添加签名（已废弃，请使用 myl_sign_params 或内部签名）"""
    timestamp = str(int(time.time()))
    params["timestamp"] = timestamp
    params["app_id"] = PASSPORT_APP_ID
    params["clientid"] = CLIENT_ID
    params["lang"] = "zh-cn"

    keys = sorted([k for k in params if k not in ("sign", "data")])
    sign_str = "&".join([f"{k}={params[k]}" for k in keys])

    sign = hmac.new(
        PASSPORT_APP_KEY.encode(), sign_str.encode(), hashlib.md5
    ).hexdigest()
    params["sign"] = sign
    return params


def myl_sign_params(params: dict[str, Any]) -> dict[str, Any]:
    """为 MYL API 参数添加简单签名

    MYL API 只需要 client_id, token, openid 和 timestamp + sign
    """
    timestamp = str(int(time.time()))
    params = {**params, "timestamp": timestamp}

    keys = sorted([k for k in params if k not in ("sign",)])
    sign_str = "&".join([f"{k}={params[k]}" for k in keys])

    sign = hmac.new(
        PASSPORT_APP_KEY.encode(), sign_str.encode(), hashlib.md5
    ).hexdigest()
    params["sign"] = sign
    return params


async def send_sms_code(phone: str, device_id: str | None = None) -> dict:
    """发送短信验证码"""
    try:
        timestamp = str(int(time.time()))
        base_device_id = device_id or generate_device_id()
        web_deviceid = generate_web_deviceid(base_device_id)
        payload = json.dumps(
            {
                "os_platform": 61,
                "sdk_channel": 1,
                "account": phone,
                "scene": "web_login",
                "DOID": generate_doid(),
                "web_deviceid": web_deviceid,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

        encrypted = aes_encrypt(payload, PASSPORT_AES_KEY)
        form = _build_sms_form(encrypted, timestamp)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Origin": "https://myl.nuanpaper.com",
            "Referer": "https://myl.nuanpaper.com/",
        }

        logger.info(
            f"[SMS Send] phone={_mask_phone(phone)}, device_id={base_device_id[:20]}..."
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{PASSPORT_API_BASE}/v1/user/account/send/code",
                data=form,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                status = resp.status
                result = await resp.json()

                logger.info(
                    f"[SMS Send] Response: status={status}, code={result.get('code')}, info={result.get('info')}"
                )

        if result.get("code") == 0:
            return {
                "success": True,
                "message": "验证码已发送",
                "device_id": base_device_id,
            }
        logger.warning(
            "SMS code request rejected: phone=%s status=%s code=%s message=%s",
            _mask_phone(phone),
            status,
            result.get("code"),
            result.get("info", result.get("message", "发送失败")),
        )
        return {
            "success": False,
            "message": result.get("info", result.get("message", "发送失败")),
        }

    except Exception as e:
        logger.exception(
            "SMS code request crashed: phone=%s error=%s",
            _mask_phone(phone),
            e,
        )
        return {"success": False, "message": f"发送失败: {e}"}


async def sms_login(phone: str, code: str, device_id: str | None = None) -> dict | None:
    """短信验证码登录"""
    dev_id = device_id or generate_device_id()

    try:
        timestamp = str(int(time.time()))
        payload = json.dumps(
            {
                "mobile": phone,
                "code": code,
                "device_id": dev_id,
                "os_platform": 61,
                "sdk_channel": 1,
                "DOID": generate_doid(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

        logger.debug(f"[SMS Login] phone={_mask_phone(phone)}")  # 不记录验证码/原始 payload

        encrypted = aes_encrypt(payload, PASSPORT_AES_KEY)

        form = _build_sms_form(encrypted, timestamp)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Origin": "https://myl.nuanpaper.com",
            "Referer": "https://myl.nuanpaper.com/",
        }

        logger.info(
            f"[SMS Login] phone={_mask_phone(phone)}, code=***, device_id={dev_id[:20]}..."
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{PASSPORT_API_BASE}/v1/user/mobile/register",
                data=form,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                status = resp.status
                result = await resp.json()

                logger.info(
                    f"[SMS Login] Response: code={result.get('code')}, info={result.get('info')}"
                )

        if result.get("code") != 0:
            logger.warning(
                "SMS login rejected: phone=%s status=%s code=%s message=%s",
                _mask_phone(phone),
                status,
                result.get("code"),
                result.get("info", result.get("message", "unknown")),
            )
            return None

        encrypted_data = result.get("data", "")
        if not encrypted_data:
            logger.warning(
                "SMS login returned empty data: phone=%s status=%s",
                _mask_phone(phone),
                status,
            )
            return None

        login_result = json.loads(aes_decrypt(encrypted_data, PASSPORT_AES_KEY))
        logger.info(f"[SMS Login] Success! nid={login_result.get('nid')}")

        return {
            "token": login_result.get("token", ""),
            "openid": str(login_result.get("nid", "")),
            "client_id": CLIENT_ID,
            "area_id": 1,
        }

    except Exception as e:
        logger.exception(
            "SMS login crashed: phone=%s error=%s",
            _mask_phone(phone),
            e,
        )
        return None


async def passport_login(account: str, password: str) -> dict | None:
    """通过 Passport API 账号密码登录"""
    try:
        timestamp = str(int(time.time()))
        droid = generate_doid()
        web_dev_id = generate_web_deviceid()

        payload = json.dumps(
            {
                "os_platform": 61,
                "sdk_channel": 1,
                "account": account,
                "password": password,
                "profile": True,
                "addresses": True,
                "DOID": droid,
                "web_deviceid": web_dev_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

        logger.debug(f"[Passport] account={_mask_phone(account)}, password=***")  # 不记录原始 payload(含明文密码)

        encrypted = aes_encrypt(payload, PASSPORT_AES_KEY)

        sign_params_dict = {
            "app_id": PASSPORT_APP_ID,
            "timestamp": timestamp,
            "sign_type": "hmac",
            "clientid": CLIENT_ID,
            "lang": "zh-cn",
            "data": encrypted,
        }

        keys = sorted([k for k in sign_params_dict if k not in ("data",)])
        sign_str = "&".join([f"{k}={sign_params_dict[k]}" for k in keys])

        sign = hmac.new(
            PASSPORT_APP_KEY.encode(), sign_str.encode(), hashlib.md5
        ).hexdigest()

        form = aiohttp.FormData()
        for k, v in sign_params_dict.items():
            if k != "data":
                form.add_field(k, str(v))
        form.add_field("data", encrypted)
        form.add_field("sign", sign)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Origin": "https://myl.nuanpaper.com",
            "Referer": "https://myl.nuanpaper.com/",
        }

        logger.info(
            f"[Passport] account={_mask_phone(account)}, DOID={droid[:20]}..., web_deviceid={web_dev_id}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{PASSPORT_API_BASE}/v1/user/login",
                data=form,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                status = resp.status
                result = await resp.json()

                logger.info(
                    f"[Passport] Response status={status} code={result.get('code')} info={result.get('info')}"
                )

        if result.get("code") != 0:
            logger.warning(
                "Passport login rejected: account=%s status=%s code=%s message=%s",
                _mask_phone(account),
                status,
                result.get("code"),
                result.get("info", result.get("message", "unknown")),
            )
            return None

        encrypted_data = result.get("data", "")
        if not encrypted_data:
            logger.warning(
                "Passport login returned empty data: account=%s status=%s",
                _mask_phone(account),
                status,
            )
            return None

        login_data = json.loads(aes_decrypt(encrypted_data, PASSPORT_AES_KEY))
        logger.info(
            f"[Passport] Login success! token={_mask_text(login_data.get('token', ''))}, nid={login_data.get('nid')}"
        )

        return {
            "token": login_data.get("token", ""),
            "openid": str(login_data.get("nid", "")),
            "client_id": CLIENT_ID,
            "area_id": 1,
        }

    except Exception as e:
        logger.exception(
            "Passport login crashed: account=%s error=%s",
            _mask_phone(account),
            e,
        )
        return None
