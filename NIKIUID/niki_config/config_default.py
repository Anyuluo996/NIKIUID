"""NIKIUID 配置项默认值声明。

参考 NTEUID/nte_config/config_default.py 的模式:
- 每个配置项用一个 GsXxxConfig 实例声明 title/desc/data 等元信息
- StringConfig 在 niki_config.py 里实例化,WebConsole 自动读取这些元信息
"""

from __future__ import annotations

from gsuid_core.utils.plugins_config.models import (
    GSC,
    GsBoolConfig,
    GsFloatConfig,
    GsIntConfig,
    GsStrConfig,
)

CONFIG_DEFAULT: dict[str, GSC] = {
    "NikiLoginUrl": GsStrConfig(
        "登录页面URL",
        "留空则用 Core 的 HOST/PORT 自动拼出登录页地址;填了就以你填的为准(需带 http(s)://)",
        "",
    ),
    "NikiLoginTTL": GsIntConfig(
        "登录会话存活秒数",
        "用户收到链接后多久内必须完成登录,超时通知「登录超时」并清理;最大 3600",
        180,
        max_value=3600,
    ),
    "NikiLoginAutoRefresh": GsBoolConfig(
        "登录后自动刷新数据",
        "登录成功后自动拉取奇想手账数据;关闭则只保存凭证,需手动发「niki刷新」",
        True,
    ),
    "NikiLoginForward": GsBoolConfig(
        "登录链接用合并转发发送",
        "开启后把登录链接包在合并转发消息里,避免部分平台链接风控",
        False,
    ),
    "NikiRenderScale": GsFloatConfig(
        "卡片渲染缩放",
        "htmlkit 渲染时的 max_width 像素值,影响卡片清晰度和宽度",
        800.0,
        min_value=400.0,
        max_value=1600.0,
    ),
}
