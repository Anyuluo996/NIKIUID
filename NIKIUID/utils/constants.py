"""NIKIUID 常量与签名工具"""

import hmac
import time
import hashlib

# 插件名称
PLUGIN_NAME = "NIKIUID"

# 登录页面URL(浏览器兜底用)
LOGIN_URL = "https://myl.nuanpaper.com/tools/journal/login"
JOURNAL_URL = "https://myl.nuanpaper.com/tools/journal"

# MYL API (登录和数据获取)
MYL_API_BASE = "https://myl-api.nuanpaper.com"
CLIENT_ID = 1106

# Passport API (登录)
PASSPORT_API_BASE = "https://passport.papegames.com"
PASSPORT_APP_ID = 1010013
PASSPORT_APP_KEY = "NsalbZh76U8VGJp1"
PASSPORT_AES_KEY = "ZTM7fu0xYnzkE5Km"  # AES encryption key used by the web login flow

# 签名密钥 (从 JS 中提取)
APP_KEY = "NsalbZh76U8VGJp1"


def _sign_params(params: dict) -> dict:
    """为 API 参数添加 HMAC-MD5 签名"""
    timestamp = str(int(time.time()))
    params["timestamp"] = timestamp
    keys = sorted(params.keys())
    sign_str = "&".join([f"{k}={params[k]}" for k in keys])
    sign = hmac.new(APP_KEY.encode(), sign_str.encode(), hashlib.md5).hexdigest()
    params["sign"] = sign
    return params
