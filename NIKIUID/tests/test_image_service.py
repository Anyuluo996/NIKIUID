"""image_service WebP 压缩测试(抽卡页面资产瘦身)。"""

import io
import asyncio
from pathlib import Path

from PIL import Image

from gsuid_core.plugins.NIKIUID.NIKIUID.utils.services.image_service import (
    webp_name,
    png_name_of_url,
    bulk_convert_webp,
    convert_png_to_webp,
)


def _png_bytes(size=300, color=(200, 60, 60, 255)) -> bytes:
    im = Image.new("RGBA", (size, size), color)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class TestNameMapping:
    def test_png_name_of_url(self):
        assert png_name_of_url("https://cdn/a/b/c_01.png") == "c_01.png"
        assert png_name_of_url("https://cdn/a/b/c_01") == "c_01.png"

    def test_webp_name(self):
        assert webp_name("c_01.png") == "c_01.webp"
        assert webp_name("c_01") == "c_01.webp"


class TestConvert:
    def test_convert_and_resize(self, tmp_path: Path):
        src = tmp_path / "big.png"
        src.write_bytes(_png_bytes(300))
        dst = tmp_path / "big.webp"
        assert convert_png_to_webp(src, dst) is True
        with Image.open(dst) as im:
            assert im.format == "WEBP"
            assert max(im.size) <= 256

    def test_small_image_keeps_size(self, tmp_path: Path):
        src = tmp_path / "s.png"
        src.write_bytes(_png_bytes(64))
        dst = tmp_path / "s.webp"
        assert convert_png_to_webp(src, dst) is True
        with Image.open(dst) as im:
            assert im.size == (64, 64)

    def test_alpha_preserved(self, tmp_path: Path):
        src = tmp_path / "a.png"
        src.write_bytes(_png_bytes(50, color=(10, 20, 30, 128)))
        dst = tmp_path / "a.webp"
        assert convert_png_to_webp(src, dst) is True
        with Image.open(dst) as im:
            assert im.mode == "RGBA"
            assert im.getpixel((0, 0))[3] == 128

    def test_missing_src(self, tmp_path: Path):
        assert convert_png_to_webp(tmp_path / "no.png", tmp_path / "no.webp") is False

    def test_corrupt_src(self, tmp_path: Path):
        src = tmp_path / "bad.png"
        src.write_bytes(b"not a png")
        assert convert_png_to_webp(src, tmp_path / "bad.webp") is False

    def test_bulk_skips_missing_and_dedupes(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "dst").mkdir()
        for n in ("a.png", "b.png"):
            (tmp_path / "src" / n).write_bytes(_png_bytes(100))
        asyncio.run(
            bulk_convert_webp(
                ["a.png", "b.png", "missing.png", "a.png"],
                tmp_path / "src",
                tmp_path / "dst",
            )
        )
        assert (tmp_path / "dst" / "a.webp").is_file()
        assert (tmp_path / "dst" / "b.webp").is_file()
        assert not (tmp_path / "dst" / "missing.webp").exists()
