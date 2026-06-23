"""核心类型定义"""

from typing import Literal, TypedDict

PoolType = Literal["limited_5", "limited_4", "permanent_5", "permanent_4"]
WardrobeFilterMode = Literal["owned", "all"]


class RefreshResult(TypedDict, total=False):
    uid: str
    refresh_status: str
    success: bool
    nickname: str
    level: int
