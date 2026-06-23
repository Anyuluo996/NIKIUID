"""NIKIUID 通用工具函数。"""

from __future__ import annotations

import time

import httpx

# 简易内存缓存,避免每次登录都去查公网 IP
_public_ip_cache: tuple[str, float] | None = None
_PUBLIC_IP_TTL = 86400.0  # 24 小时


async def get_public_ip(host: str = "127.0.0.1") -> str:
    """探测本机公网 IP,用于拼接对外可访问的登录页 URL。

    依次尝试多个 IP 探测服务,失败回退到传入的 host。
    """
    global _public_ip_cache
    if _public_ip_cache and time.time() - _public_ip_cache[1] < _PUBLIC_IP_TTL:
        return _public_ip_cache[0]

    for url, extractor in [
        ("https://event.kurobbs.com/event/ip", lambda r: r.text),
        ("https://api.ipify.org/?format=json", lambda r: r.json()["ip"]),
        ("https://httpbin.org/ip", lambda r: r.json()["origin"]),
    ]:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(url, timeout=4)
                ip = extractor(r)
                if ip:
                    _public_ip_cache = (ip, time.time())
                    return ip
        except Exception:
            continue

    return host
