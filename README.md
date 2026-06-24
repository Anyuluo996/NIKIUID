# NIKIUID

无限暖暖(Infinity Nikki)数据查询插件,适用于 [gsuid_core](https://github.com/GenshinUID/gsuid_core)。

## 功能一览

| 功能 | 说明 |
|------|------|
| **奇想手账** | 全区域探索进度(伊赞之土/心愿原野/花焰群岛/无忧岛/丹青屿)+ 共鸣统计 |
| **共鸣衣橱** | 已共鸣套装图标 + 各套装共鸣抽数,支持按星级/全部筛选 |
| **体力查询** | 活跃能量(按文档公式实时计算)、朝夕心愿(每日 04:00 重置)、美鸭梨挖掘派遣详情 |
| **日历** | 版本内容一览图片(活动日历/新套装/新玩法),自动每日抓取 |
| **账号管理** | 网页短信验证登录 + 账号密码直登(仅限私聊) |
| **帮助** | PIL 渲染图片帮助页,无限暖暖主题图标 |

## 命令

所有命令支持三种前缀:`niki`、`nk`、无前缀(取决于 force_prefix 配置)。

### 数据查询

| 命令 | 拼音首字母 | 英文 | 说明 |
|------|-----------|------|------|
| `卡片` | `kp` | — | 查看奇想手账(全区域探索 + 共鸣统计) |
| `抽卡` | `ck` | — | 查看共鸣衣橱(套装图标 + 抽数) |
| `体力` | `tl` | `stamina` / `energy` | 查询活跃能量/朝夕心愿/派遣任务(实时) |
| `日历` | `rl` | `calendar` | 查看最新版本内容一览图片 |
| `刷新` | `sx` | `sync` | 重新拉取奇想手账数据 |

**抽卡参数**:`nk抽卡全`(全部套装) / `nk抽卡5`(仅五星) / `nk抽卡4`(仅四星)

**日历参数**:`nk日历`(最新版本) / `nk日历 2.7`(指定版本) / `nk日历列表`(可用版本列表)

### 账号管理

| 命令 | 拼音首字母 | 说明 |
|------|-----------|------|
| `登录` | `dl` | 获取网页登录链接(短信验证,群聊/私聊均可) |
| `登录 账号,密码` | — | 账号密码直登(**仅限私聊**,群聊会被拒绝) |
| `退出登录` | `tcdl` / `dc` | 清除当前激活账号 |
| `全部登出` | `qbdc` | 清除全部账号 |

### 其他

| 命令 | 拼音首字母 | 说明 |
|------|-----------|------|
| `帮助` | `bz` | 查看帮助图片 |

## 渲染

- **卡片**(体力/手账/衣橱):htmlkit 渲染 + 2x 超采样清晰输出,MiSans 字体内联(无需安装系统字体)
- **帮助**:PIL 渲染,gsuid_core 帮助框架 + 无限暖暖主题图标素材
- **日历**:从 [NIKIUID-calendar](https://cnb.cool/anyuluo/NIKIUID-calendar) 仓库拉取原图(CNB 分发,中国直连)

## 数据源

| 数据 | 来源 | 说明 |
|------|------|------|
| 奇想手账/共鸣/体力 | MYL `note/book/info` API | Snappy 压缩,`info_from_gm` 含 45+ 字段 |
| 体力实时值 | 前端公式计算 | `min(energy + (now-timestamp)/300, 350)`,5 分钟回复 1 点 |
| 派遣任务 | `info_from_gm.dispatch` | 总时长 20 小时,按 `start_time` 计算剩余 |
| 朝夕心愿 | `info_from_gm.daily_task` | 每日 04:00(北京时间)重置显示 |
| 日历图片 | [NIKIUID-calendar](https://cnb.cool/anyuluo/NIKIUID-calendar) | GitHub Actions / CNB 流水线每日自动爬取官网 |

## 配置项

所有配置在 gsuid_core WebConsole 可视化编辑:

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `NikiLoginUrl` | `""` | 自定义登录页 URL(留空则自动生成) |
| `NikiLoginTTL` | `300` | 登录链接有效期(秒) |
| `NikiLoginAutoRefresh` | `True` | 登录后自动拉取奇想手账数据 |
| `NikiRenderScale` | `800.0` | 卡片渲染缩放(影响清晰度和宽度,400~1600) |

配置定义见 [`niki_config/config_default.py`](NIKIUID/niki_config/config_default.py)。

## 安装

```bash
# 方式 1: 直接 clone 到 gsuid_core 插件目录
cd gsuid_core/gsuid_core/plugins
git clone https://github.com/Anyuluo996/NIKIUID.git

# 方式 2: CNB(中国直连)
git clone https://cnb.cool/anyuluo/NIKIUID.git
```

### 依赖

插件依赖 gsuid_core 自带的基础库,**无需额外安装**:

- `aiohttp` — API 请求
- `Pillow` — 帮助图片渲染
- `sqlmodel` — 数据库
- `python-snappy` — API 响应解压(gsuid_core 已内置)
- `jinja2` — HTML 模板

字体(`MiSans-Bold.ttf`)复用 gsuid_core 自带文件,不重复发布。

## WebConsole 管理后台

在 gsuid_core WebConsole 的「无限暖暖暖用户管理」页面可:
- 查看所有绑定用户
- 查看/编辑 token、昵称、等级等字段
- 删除失效账号

## 日历仓库

日历图片由独立仓库维护,每日自动更新:

- **CNB**(中国直连): https://cnb.cool/anyuluo/NIKIUID-calendar
- **GitHub**(备份): https://github.com/Anyuluo996/NIKIUID-calendar

仓库内含:
- `crawler/crawl.py` — 官网新闻爬虫
- `.github/workflows/crawl.yml` — GitHub Actions 定时流水线
- `.cnb.yml` — CNB 定时流水线
- `manifest.json` — 版本元数据清单
- `images/{版本号}/` — 按版本分目录的图片

## 致谢

- [NTEUID](https://github.com/NoneGTGB/NTEUID) — 数据库基类、登录链路、帮助框架参考
- [gsuid_core](https://github.com/GenshinUID/gsuid_core) — 插件运行平台
