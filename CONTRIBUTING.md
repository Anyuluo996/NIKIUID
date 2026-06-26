# NIKIUID 开发规范

本文档总结了项目开发过程中的实际教训,作为未来贡献者的指南。所有规则都有**血泪原因** —— 每条都对应过一个真实的 bug。

## 开发环境

```bash
cd gsuid_core

# 安装开发依赖
.venv/Scripts/pip3.exe install ruff pre-commit pytest pytest-asyncio

# 安装 pre-commit 钩子(每次 commit 自动跑 ruff)
cd gsuid_core/plugins/NIKIUID
pre-commit install

# 运行检查
.venv/Scripts/ruff.exe check NIKIUID/          # 代码检查
.venv/Scripts/ruff.exe format NIKIUID/          # 格式化
.venv/Scripts/python.exe -m pytest NIKIUID/tests/ -v  # 测试
```

---

## 一、代码规范

### 1.1 import 写法(踩过的坑最多)

```python
# ✅ 正确
from datetime import datetime, timedelta, timezone
from gsuid_core.logger import logger

# ❌ 错误 — 会导致 datetime.datetime.now() 崩溃
import datetime
datetime.datetime.now()  # AttributeError!

# ❌ 错误 — gsuid_core 用 structlog,不是标准 logging
import logging
logger = logging.getLogger("niki.xxx")  # 日志不显示!
```

**规则:**
- 用 `from X import Y`,不用 `import X` + `X.Y()`
- 日志统一 `from gsuid_core.logger import logger`(structlog,带 trace_id)
- 禁止 `import logging` / `logging.getLogger()`(与 gsuid_core 日志系统不互通)

### 1.2 数据库模型

```python
# ✅ 继承 User 基类(复用 user_id/bot_id/cookie/status)
from gsuid_core.utils.database.base_models import User, with_session

class NikiUser(User, table=True):
    uid: str = Field(default="", index=True)  # 只声明游戏特有字段
    # user_id / bot_id / cookie / status 由基类提供,不重复声明
```

**规则:**
- 用户表继承 `User`(不是 `BaseIDModel`),复用 `user_id`/`bot_id`/`cookie`/`status`
- token 存在 `cookie` 字段(用 property 映射 `token` 名称)
- 所有 DB 方法用 `@classmethod @with_session`,session 自动 commit
- 新表要在 `exec_list` 加 `CREATE INDEX`
- 表要注册 `@site.register_admin`(WebConsole 可见)

### 1.3 命令注册

```python
sv = SV("niki体力")

# on_command: 带参数的命令(如 nk抽卡5)
@sv.on_command(("体力", "能量", "stamina", "energy", "tl"), block=True)

# on_fullmatch: 精确匹配(如 nk帮助)
@sv.on_fullmatch(("帮助", "bz", "help"), block=True)
```

**规则:**
- 每个命令至少支持:中文全称 + 拼音首字母 + 英文缩写
- 前缀用 `niki_prefix()` 动态获取,不写死 `"niki"`
- 未登录检查统一用 `require_user(bot, ev)`

### 1.4 安全红线

```python
# ✅ 密码/验证码永远不进日志
logger.debug(f"account={_mask_phone(account)}, password=***")

# ❌ 禁止 — 密码明文写入日志文件
logger.debug(f"payload: {payload}")  # payload 含 password!

# ✅ 用户输入的 uid 要校验路径穿越
if not _SAFE_UID_RE.match(uid):
    raise ValueError(f"非法 uid: {uid!r}")
```

**规则:**
- 日志里手机号用 `_mask_phone()`(前3后4),token 用 `_mask_text()`
- 禁止记录包含 password/code 的原始 payload
- 用户输入的 uid/openid 要用正则白名单校验(防 `../` 路径穿越)
- 账号密码登录仅限私聊(`if ev.group_id: return`)

---

## 二、渲染规范

### 2.1 htmlkit 卡片渲染

```python
# ✅ 正确
html = NIKI_TEMPLATES.get_template("stamina.html").render(**ctx)
img = await render_html_to_image(html, max_width=760.0)
```

**规则:**
- 模板用 `NIKI_TEMPLATES`(单一 Jinja Environment),不每次 `new Environment()`
- 字体通过 `@font-face` base64 内联(复用 gsuid_core 的 `FONT_ORIGIN_PATH`),不随插件重复发布 ttf
- 模板里禁止用 emoji(`✅⚡` 等在 htmlkit 下显示为乱码/码点数字)
- 背景图用 CSS `url("images/bg/xxx.jpg")`,`render_image.py` 会自动转 base64

### 2.2 PIL 帮助图片

```python
# ✅ 字体复用 gsuid_core 自带
from gsuid_core.utils.fonts.fonts import core_font
font = core_font(38)
```

**规则:**
- PIL 字体用 `core_font(size)`(指向 gsuid_core 的 `MiSans-Bold.ttf`)
- 图标文件裁剪为正方形(ratio=1.0),框架强制 resize 到 128×128

---

## 三、测试规范

### 3.1 什么必须测试

| 优先级 | 测试内容 | 原因 |
|--------|---------|------|
| P0 | 计算公式(体力/朝夕心愿/派遣) | 直接影响用户看到的数据正确性 |
| P0 | 安全(路径穿越/脱敏/加密) | 安全漏洞不可妥协 |
| P1 | 数据解析(抽卡/套装) | 格式多样,容易遗漏分支 |
| P2 | 工具函数(缓存/格式化) | 被多处复用 |

### 3.2 测试写法

```python
# ✅ 纯函数:给定输入 → 验证输出
def test_energy_regen():
    r = _calc_estimated_energy(6, 1782091216, 1782170450)
    assert r["current"] == 270  # 文档实测值

# ✅ 安全:注入应抛异常
def test_path_traversal():
    with pytest.raises(ValueError):
        get_user_dir(base, "../../../etc")

# ✅ 往返:加密→解密 = 原文
def test_aes_roundtrip():
    assert aes_decrypt(aes_encrypt("无限暖暖", key), key) == "无限暖暖"
```

**规则:**
- 测试文件放 `NIKIUID/tests/`,命名 `test_<模块>.py`
- 纯函数优先;需要重构提取纯函数后再测(如 `_calc_estimated_energy`)
- 回归测试用文档实测值(如 `energy=6 → 270`)防止公式改错
- 提交前必须 `pytest` 全绿

### 3.3 ruff 检查

```bash
# 提交前必须通过
ruff check NIKIUID/     # 0 errors
ruff format NIKIUID/    # 格式化
```

**规则:**
- 禁止提交有 ruff error 的代码
- `F821`(未定义变量)尤其重要 — 曾因重构遗漏导致运行时崩溃

---

## 四、Git 规范

### 4.1 Commit 消息

```
<类型>: <简短描述>

<详细说明(可选)>
```

类型:`feat`(新功能) / `fix`(修复) / `refactor`(重构) / `docs`(文档) / `test`(测试) / `chore`(杂项)

### 4.2 分支

- `main`:稳定版本,直接推
- 功能开发可以开分支,但小改动直接推 main 也行

### 4.3 敏感信息

- `.gitignore` 已排除 `data.json`/`avatar.png`/`user_data/`/`__pycache__/`
- 禁止提交真实手机号/密码/token 到代码或日志
- 测试用的账号密码用占位符(`账号,密码`)

---

## 五、架构速查

```
NIKIUID/
├── NIKIUID/
│   ├── __init__.py              # 插件入口 + @gss.on_bot_connect 迁移
│   ├── version.py               # 版本号
│   ├── niki_login/              # 登录(短信+密码+网页路由)
│   ├── niki_refresh/            # 数据刷新
│   ├── niki_card/               # 奇想手账 + 共鸣衣橱
│   ├── niki_stamina/            # 体力查询(实时)
│   ├── niki_calendar/           # 日历(CNB 图片分发)
│   ├── niki_help/               # 帮助图片(PIL)
│   ├── niki_config/             # 配置(StringConfig)
│   ├── utils/
│   │   ├── database/            # NikiUser(User) + NikiUserAdmin
│   │   ├── services/            # 业务服务(stamina/resonance/journal/refresh)
│   │   ├── auth/                # passport 认证 + crypto 加密
│   │   ├── resource/            # RESOURCE_PATH(路径常量)
│   │   ├── render_image.py      # htmlkit 渲染(超采样+字体内联)
│   │   ├── render_journal_card.py
│   │   ├── render_wardrobe_card.py
│   │   ├── storage_cache.py     # NikiJournalData(DB) + 文件缓存
│   │   ├── storage_assets.py    # 套装图片下载(core download())
│   │   ├── session.py           # require_user() 统一鉴权
│   │   ├── migrate.py           # 文件→DB 自动迁移
│   │   ├── cache.py             # TimedCache(TTL+LRU)
│   │   └── msgs.py              # 消息文案
│   ├── templates/               # Jinja2 HTML 模板
│   ├── images/                  # 图标 + 背景图
│   └── tests/                   # 单元测试
├── ICON.png                     # 插件图标
├── pyproject.toml               # 项目配置
├── ruff.toml                    # ruff 规则
└── .pre-commit-config.yaml      # pre-commit 钩子
```

---

## 六、常见陷阱速查

| 陷阱 | 症状 | 解决 |
|------|------|------|
| `import datetime` | `AttributeError: datetime.datetime` | 改 `from datetime import datetime` |
| `logging.getLogger()` | 日志不显示 | 改 `from gsuid_core.logger import logger` |
| 模板用 emoji | 显示 `2705` 或方块 | 删除 emoji,用纯文本 |
| htmlkit 不执行 JS | 卡片空白 | 改 Jinja2 服务端渲染 |
| `file:///` 中文路径 | 图片不显示 | `render_image.py` 自动转 base64 |
| 系统没装中文字体 | 渲染方块 | `@font-face` 内联 MiSans |
| `BaseIDModel` 无 `insert_data` | `AttributeError` | 用 `@with_session` + `session.add()` |
| `download_suit_images(logger=)` | `unexpected keyword argument` | 检查参数名是否匹配 |
| GitHub 在中国不可访问 | 图片加载失败 | 日历用 CNB 分发 |
