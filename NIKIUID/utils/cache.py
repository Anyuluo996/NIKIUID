"""简易 TTL 缓存,用于登录会话。

参考 NTEUID/utils/cache.py 的 TimedCache,精简版:
- 带 TTL 过期
- 带 LRU 淘汰(maxsize)
- 线程安全够用(单事件循环内)
"""

from __future__ import annotations

import time
from typing import Any
from collections import OrderedDict


def _now() -> float:
    """单调时钟,不受系统时间校准影响。"""
    return time.monotonic()


class TimedCache:
    """带 TTL + LRU 的内存缓存。"""

    def __init__(self, timeout: float = 300.0, maxsize: int = 32) -> None:
        if timeout < 0:
            raise ValueError("timeout must be >= 0")
        if maxsize <= 0:
            raise ValueError("maxsize must be > 0")
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._timeout = timeout
        self._maxsize = maxsize

    def set(self, key: str, value: Any) -> None:
        self._sweep()
        if key in self._store:
            self._store.move_to_end(key)
        else:
            while len(self._store) >= self._maxsize:
                self._store.popitem(last=False)
        self._store[key] = (value, _now() + self._timeout)

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expire_at = entry
        if expire_at <= _now():
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return value

    def pop(self, key: str) -> Any | None:
        entry = self._store.pop(key, None)
        if entry is None:
            return None
        value, expire_at = entry
        if expire_at <= _now():
            return None
        return value

    def delete(self, key: str) -> None:
        """兼容旧 niki 的 login_cache.delete 接口。"""
        self._store.pop(key, None)

    def items(self) -> list[tuple[str, Any]]:
        """返回所有未过期的 (key, value) 列表(快照)。"""
        self._sweep()
        return [(k, v) for k, (v, _) in self._store.items()]

    def clear(self) -> None:
        self._store.clear()

    def _sweep(self) -> None:
        now = _now()
        expired = [k for k, (_, exp) in self._store.items() if exp <= now]
        for k in expired:
            self._store.pop(k, None)
