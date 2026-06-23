# NIKIUID - 无限暖暖插件 (gsuid_core)

无限暖暖(Infinity Nikki)奇想手账插件,从 AstrBot 平台迁移而来。

## 功能

- 📱 网页短信登录(参考 NTEUID 登录设计)
- 🔄 登录后自动刷新奇想手账数据
- 🃏 奇想手账卡片生成
- 🎰 抽卡统计 / 记录卡片(含进化套装归并)
- ❓ 帮助信息

## 命令

| 命令 | 别名 | 说明 |
|---|---|---|
| `niki登录` | `nk登录` | 获取一次性网页登录链接 |
| `niki刷新` | `nk刷新` | 重新拉取奇想手账数据 |
| `niki卡片` | `nk卡片` | 生成奇想手账卡片 |
| `niki抽卡` | `nk抽卡` | 生成抽卡统计卡片 |
| `niki帮助` | `nk帮助` | 查看帮助 |

抽卡支持紧凑命令:`nkck限定5星` / `niki抽卡全`(查看全部套装)。

## 渲染说明

卡片图片通过 gsuid_core 内置的 htmlkit (`render_html_to_bytes`) 渲染,
不依赖 Playwright。共鸣数据默认走 MYL API 模式;如需浏览器抓取模式,
安装可选依赖 `pip install playwright && playwright install chromium` 后
将配置 `NikiResonanceMode` 设为 `browser`。

## 配置项

所有配置在 gsuid_core WebConsole 可视化编辑,见 `niki_config/config_default.py`。

## 致谢

- 原 AstrBot 版 niki 插件
- NTEUID 插件(登录链路设计参考)
