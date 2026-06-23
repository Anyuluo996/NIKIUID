"""HTML → 图片渲染(htmlkit 实现)

替代原 niki 的 Playwright 渲染层。核心调用 gsuid_core 内置的
`render_html_to_bytes`(基于 C 库 htmlkit / pyrenderhtml)。

关键差异:
- 返回 bytes 而非文件路径,调用方用 `MessageSegment.image(bytes)` 发送
- htmlkit 对 CSS 支持弱于 Chromium,不支持 backdrop-filter / CSS 变量 / 动画;
  HTML 模板需用内联样式 + 简单布局
- 本地图片引用需转为 file:// 绝对路径(见 `_absolutize_img_src`)
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import Any

from gsuid_core.logger import logger
from gsuid_core.utils.html_render import render_html_to_bytes

from .resource.RESOURCE_PATH import USER_DATA_PATH


# 渲染最大宽度(像素),影响清晰度。由配置 NikiRenderScale 控制,默认 800
DEFAULT_MAX_WIDTH = 800.0

# 匹配 HTML 里的 <img src="..."> 相对路径,转成 file:// 绝对路径
# 支持 images/icon/xxx 和 单独的文件名
_IMG_SRC_RE = re.compile(r'src="(images/[^"]+)"')
_IMG_SRC_RE_USER = re.compile(r'src="(users/[^"]+)"')
# 匹配 CSS url("images/...") / url(images/...) 形式(背景图等)
_CSS_URL_RE = re.compile(r'url\(\s*["\']?(images/[^"\')]+)["\']?\s*\)')
_CSS_URL_RE_USER = re.compile(r'url\(\s*["\']?(users/[^"\')]+)["\']?\s*\)')


def _path_to_file_url(abs_path: Path) -> str:
    """把绝对路径转成 file:/// URL(Windows 反斜杠转正斜杠)。"""
    return f"file:///{str(abs_path).replace(chr(92), '/')}"


def _absolutize_img_src(html: str, extra_base: Path | None = None) -> str:
    """把 HTML 里的相对图片路径转成 file:// 绝对路径,便于 htmlkit 读取。

    支持两种引用形式:
    - <img src="images/..."> → src="file:///..."
    - url("images/...") / url(images/...) → url("file:///...")

    支持两种相对前缀:
    - images/...  → 相对插件静态资源目录
    - users/...   → 相对 USER_DATA_PATH
    """
    plugin_root = Path(__file__).resolve().parents[1]

    def _make_src_replacer(prefix_dir: Path) -> Any:
        prefix_resolved = prefix_dir.resolve()

        def repl(m: re.Match[str]) -> str:
            rel = m.group(1)
            abs_path = (prefix_dir / rel).resolve()
            # 路径穿越防护:resolve 后必须仍在 prefix_dir 之下
            if not abs_path.is_relative_to(prefix_resolved):
                logger.warning(f"拒绝越界路径: {rel}")
                return m.group(0)
            if abs_path.exists():
                url = _path_to_file_url(abs_path)
                return f'src="{url}"'
            # 文件不存在,保留原样(让模板的 onerror 兜底)
            return m.group(0)

        return repl

    def _make_url_replacer(prefix_dir: Path) -> Any:
        prefix_resolved = prefix_dir.resolve()

        def repl(m: re.Match[str]) -> str:
            rel = m.group(1)
            abs_path = (prefix_dir / rel).resolve()
            # 路径穿越防护
            if not abs_path.is_relative_to(prefix_resolved):
                logger.warning(f"拒绝越界路径: {rel}")
                return m.group(0)
            if abs_path.exists():
                url = _path_to_file_url(abs_path)
                return f'url("{url}")'
            return m.group(0)

        return repl

    # <img src="images/..."> 与 <img src="users/...">
    html = _IMG_SRC_RE.sub(_make_src_replacer(plugin_root), html)
    html = _IMG_SRC_RE_USER.sub(_make_src_replacer(USER_DATA_PATH), html)
    # CSS url(images/...) 与 url(users/...)
    html = _CSS_URL_RE.sub(_make_url_replacer(plugin_root), html)
    html = _CSS_URL_RE_USER.sub(_make_url_replacer(USER_DATA_PATH), html)

    # 处理 extra_base(用户数据目录下的 avatar.png 等)
    if extra_base is not None:
        extra_re = re.compile(r'src="(avatar\.png)"')

        def repl_extra(m: re.Match[str]) -> str:
            abs_path = (extra_base / m.group(1)).resolve()
            if abs_path.exists():
                url = _path_to_file_url(abs_path)
                return f'src="{url}"'
            return m.group(0)

        html = extra_re.sub(repl_extra, html)

    return html


def _inline_local_images(html: str, base_dir: Path) -> str:
    """把被引用的本地图片内联成 base64 data URI。

    htmlkit 对 file:// 的支持不确定,base64 最保险。
    同时处理 <img src="file:///..."> 与 CSS url("file:///...")。
    """
    # 同时匹配 src="file:///..." 和 url("file:///...") 和 url(file:///...)
    pattern = re.compile(r'(?:src="file:///([^"]+)"|url\(\s*["\']?file:///([^"\')]+)["\']?\s*\))')

    def repl(m: re.Match[str]) -> str:
        # group(1) 是 src 形式,group(2) 是 url() 形式
        path_str = m.group(1) or m.group(2)
        img_path = Path(path_str)
        if not img_path.exists():
            return m.group(0)
        try:
            data = img_path.read_bytes()
            ext = img_path.suffix.lower().lstrip(".")
            mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
            b64 = base64.b64encode(data).decode()
            data_uri = f"data:{mime};base64,{b64}"
            if m.group(1) is not None:
                return f'src="{data_uri}"'
            return f'url("{data_uri}")'
        except Exception as e:
            logger.warning(f"内联图片失败 {img_path}: {e}")
            return m.group(0)

    return pattern.sub(repl, html)


# ── 字体内联(参考 NTEUID 思路:字体随插件发布,不依赖系统 fontconfig) ──
_FONT_CACHE: dict[str, str] = {}


def _get_font_face_css() -> str:
    """生成 @font-face CSS,把插件自带的 MiSans 字体内联成 base64。

    htmlkit 走系统 fontconfig,容器里没装中文字体会渲染方块/缺字。
    把 ttf 内联成 @font-face 后,htmlkit 直接从 CSS 加载,完全脱离系统字体。
    结果缓存避免每次渲染都读 8MB 文件做 base64。

    字体文件复用 gsuid_core 自带的 MiSans-Bold.ttf(不重复发布)。
    """
    if "css" in _FONT_CACHE:
        return _FONT_CACHE["css"]

    # 复用 gsuid_core 自带字体,不随插件重复发布
    from gsuid_core.utils.fonts.fonts import FONT_ORIGIN_PATH

    font_path = Path(FONT_ORIGIN_PATH)
    if not font_path.exists():
        logger.warning(f"字体文件不存在: {font_path}")
        return ""

    data = font_path.read_bytes()
    b64 = base64.b64encode(data).decode()
    # 注册多个常用名,让模板里的 font-family 都能命中
    css = f"""
    <style>
    @font-face {{
        font-family: 'MiSans';
        src: url(data:font/ttf;base64,{b64}) format('truetype');
        font-weight: bold;
        font-style: normal;
    }}
    @font-face {{
        font-family: 'MiSans-Bold';
        src: url(data:font/ttf;base64,{b64}) format('truetype');
        font-weight: normal;
        font-style: normal;
    }}
    </style>
    """
    _FONT_CACHE["css"] = css
    return css


def _inject_font(html: str) -> str:
    """把 @font-face 注入到 HTML 的 <head> 里(在所有样式之前)。"""
    font_css = _get_font_face_css()
    if not font_css:
        return html
    # 注入到 <head> 之后;没 head 就插到 <html> 后;都没就加到开头
    if "<head>" in html:
        return html.replace("<head>", f"<head>{font_css}", 1)
    if "<html" in html:
        return re.sub(r"(<html[^>]*>)", rf"\1{font_css}", html, count=1)
    return font_css + html


async def render_html_to_image(
    html_content: str,
    pool_type: str = "limited_5",
    num_items: int = 0,
    *,
    user_data_dir: Path | None = None,
    max_width: float = DEFAULT_MAX_WIDTH,
    scale: float = 2.0,
    **_kwargs: Any,
) -> bytes | None:
    """用 htmlkit 把 HTML 渲染成 PNG bytes。

    与原 Playwright 版签名兼容(接受 pool_type/num_items 等额外参数,但忽略
    高度计算 —— htmlkit 自动按内容高度出图)。

    超采样渲染:按 `max_width × scale` 的像素预算渲染,再用 PIL 缩回 max_width,
    得到更清晰的文字和图标(类似手机屏幕的高 DPI)。

    Args:
        html_content: HTML 字符串
        pool_type: 卡池类型(保留兼容,本实现不用)
        num_items: 套装数量(保留兼容,本实现不用)
        user_data_dir: 用户数据目录,用于解析 avatar.png 等本地图片
        max_width: 最终输出的显示宽度(CSS 像素)
        scale: 超采样倍数,2.0 = 2x 渲染再缩回(默认清晰)

    Returns:
        PNG 图片字节,失败返回 None
    """
    try:
        from PIL import Image

        # 1. 注入内联字体(让 htmlkit 不依赖系统 fontconfig)
        html = _inject_font(html_content)
        # 2. 把相对图片路径转 file:// 绝对路径
        html = _absolutize_img_src(html, extra_base=user_data_dir)
        # 3. 把 file:// 图片内联成 base64(最兼容)
        if user_data_dir is not None:
            html = _inline_local_images(html, user_data_dir)
        else:
            html = _inline_local_images(html, USER_DATA_PATH)

        # 3. 超采样渲染:用更大的像素预算渲染(htmlkit 按比例缩放所有元素)
        render_width = max_width * scale
        image_bytes = await render_html_to_bytes(html, max_width=render_width)
        if not image_bytes:
            logger.warning("[render] htmlkit 返回空 bytes")
            return None

        # 4. 用 PIL 高质量缩回显示尺寸(LANCZOS 抗锯齿)
        hi_img = Image.open(io.BytesIO(image_bytes))
        if hi_img.mode != "RGBA":
            hi_img = hi_img.convert("RGBA")
        target_w = int(max_width)
        target_h = int(hi_img.height * (target_w / hi_img.width))
        out_img = hi_img.resize((target_w, target_h), Image.LANCZOS)

        # 5. 输出 PNG(无损,保留清晰度)
        buf = io.BytesIO()
        out_img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.exception(f"[render] htmlkit 渲染失败: {e}")
        return None
