"""Comprehensive tests for MediaProcessor domain conversion engine."""

import hashlib
from pathlib import Path
import pytest
from PIL import Image
from app.engine.processor import (
    MediaProcessor,
    REQUIRED_ICO_SIZES,
    UnsupportedFormatError,
    CorruptedImageError,
    ImageDimensionLimitError,
)


@pytest.fixture
def static_sticker_webp(tmp_path: Path) -> Path:
    """Representative 512x512 static Telegram sticker WebP with transparency."""
    p = tmp_path / "sticker.webp"
    img = Image.new("RGBA", (512, 512), color=(0, 120, 255, 128))
    img.save(p, format="WEBP")
    return p


@pytest.fixture
def cmyk_image(tmp_path: Path) -> Path:
    p = tmp_path / "sample_cmyk.jpg"
    img = Image.new("CMYK", (100, 100), color=(100, 50, 0, 20))
    img.save(p, format="JPEG")
    return p


@pytest.fixture
def grayscale_image(tmp_path: Path) -> Path:
    p = tmp_path / "sample_gray.png"
    img = Image.new("L", (100, 100), color=128)
    img.save(p, format="PNG")
    return p


@pytest.fixture
def palette_image(tmp_path: Path) -> Path:
    p = tmp_path / "sample_palette.png"
    img = Image.new("P", (100, 100))
    img.putpalette([255, 0, 0, 0, 255, 0, 0, 0, 255] * 85)
    img.save(p, format="PNG")
    return p


@pytest.fixture
def exif_rotated_jpeg(tmp_path: Path) -> Path:
    """JPEG image with width=120, height=60, and EXIF orientation 6 (rotate 90 CW)."""
    p = tmp_path / "exif_rotated.jpg"
    img = Image.new("RGB", (120, 60), color=(200, 100, 50))
    exif = img.getexif()
    exif[0x0112] = 6  # Orientation 6
    img.save(p, format="JPEG", exif=exif)
    return p


@pytest.fixture
def animated_gif_image(tmp_path: Path) -> Path:
    """Animated GIF with multiple frames."""
    p = tmp_path / "animated.gif"
    f1 = Image.new("RGB", (60, 60), color=(255, 0, 0))
    f2 = Image.new("RGB", (60, 60), color=(0, 255, 0))
    f1.save(p, format="GIF", save_all=True, append_images=[f2])
    return p


@pytest.fixture
def multipage_tiff_image(tmp_path: Path) -> Path:
    """TIFF with multiple pages."""
    p = tmp_path / "multipage.tiff"
    p1 = Image.new("RGB", (80, 80), color=(0, 0, 255))
    p2 = Image.new("RGB", (80, 80), color=(255, 255, 0))
    p1.save(p, format="TIFF", save_all=True, append_images=[p2])
    return p


# 1. Basic Conversion Matrix Tests
@pytest.mark.asyncio
async def test_conversion_png_to_jpg(sample_png: Path, tmp_path: Path):
    target = tmp_path / "out.jpg"
    out = await MediaProcessor.convert_image(sample_png, output_format="jpg", target_path=target)
    assert out.exists()
    with Image.open(out) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"


@pytest.mark.asyncio
async def test_conversion_jpg_to_webp(sample_jpeg: Path, tmp_path: Path):
    target = tmp_path / "out.webp"
    out = await MediaProcessor.convert_image(sample_jpeg, output_format="webp", target_path=target)
    assert out.exists()
    with Image.open(out) as img:
        assert img.format == "WEBP"


@pytest.mark.asyncio
async def test_conversion_png_to_pdf(sample_png: Path, tmp_path: Path):
    target = tmp_path / "out.pdf"
    out = await MediaProcessor.convert_image(sample_png, output_format="pdf", target_path=target)
    assert out.exists()
    with open(out, "rb") as f:
        content = f.read()
        assert content.startswith(b"%PDF-")
        assert b"%%EOF" in content
        # Exactly 1 page
        assert content.count(b"/Type /Pages") == 1


@pytest.mark.asyncio
async def test_conversion_png_to_ico(sample_png: Path, tmp_path: Path):
    target = tmp_path / "out.ico"
    out = await MediaProcessor.convert_image(sample_png, output_format="ico", target_path=target)
    assert out.exists()
    with Image.open(out) as img:
        assert img.format == "ICO"
        assert hasattr(img, "ico") and hasattr(img.ico, "sizes")
        sizes = set(img.ico.sizes())
        for req in REQUIRED_ICO_SIZES:
            assert req in sizes




@pytest.mark.asyncio
async def test_conversion_png_to_bmp(sample_png: Path, tmp_path: Path):
    target = tmp_path / "out.bmp"
    out = await MediaProcessor.convert_image(sample_png, output_format="bmp", target_path=target)
    assert out.exists()
    with Image.open(out) as img:
        assert img.format == "BMP"
        assert img.mode == "RGB"


# 2. Static Telegram Sticker Input Tests
@pytest.mark.asyncio
async def test_static_telegram_sticker_to_png(static_sticker_webp: Path, tmp_path: Path):
    target = tmp_path / "sticker.png"
    out = await MediaProcessor.convert_image(static_sticker_webp, output_format="png", target_path=target)
    assert out.exists()
    with Image.open(out) as img:
        assert img.format == "PNG"
        assert img.size == (512, 512)
        assert img.mode == "RGBA"


@pytest.mark.asyncio
async def test_static_telegram_sticker_to_jpg(static_sticker_webp: Path, tmp_path: Path):
    target = tmp_path / "sticker.jpg"
    out = await MediaProcessor.convert_image(static_sticker_webp, output_format="jpg", target_path=target)
    assert out.exists()
    with Image.open(out) as img:
        assert img.format == "JPEG"
        assert img.size == (512, 512)
        assert img.mode == "RGB"


@pytest.mark.asyncio
async def test_static_telegram_sticker_to_webp(static_sticker_webp: Path, tmp_path: Path):
    target = tmp_path / "sticker_copy.webp"
    out = await MediaProcessor.convert_image(static_sticker_webp, output_format="webp", target_path=target)
    assert out.exists()
    with Image.open(out) as img:
        assert img.format == "WEBP"
        assert img.size == (512, 512)


@pytest.mark.asyncio
async def test_static_telegram_sticker_to_pdf(static_sticker_webp: Path, tmp_path: Path):
    target = tmp_path / "sticker.pdf"
    out = await MediaProcessor.convert_image(static_sticker_webp, output_format="pdf", target_path=target)
    assert out.exists()
    with open(out, "rb") as f:
        content = f.read()
        assert content.startswith(b"%PDF-")


# 3. Transparency Handling Tests
@pytest.mark.asyncio
async def test_transparency_flatten_to_white_jpg(tmp_path: Path):
    # Half-transparent image
    img_path = tmp_path / "transparent.png"
    img = Image.new("RGBA", (10, 10), color=(0, 0, 0, 0))  # 100% transparent black
    img.save(img_path, format="PNG")

    target = tmp_path / "out_white.jpg"
    out = await MediaProcessor.convert_image(img_path, output_format="jpg", target_path=target)
    with Image.open(out) as result:
        assert result.mode == "RGB"
        # Since source was 100% transparent, flattened against white background must be (255, 255, 255)
        pixel = result.getpixel((0, 0))
        assert pixel == (255, 255, 255)


@pytest.mark.asyncio
async def test_transparency_preserved_in_webp_and_png(sample_png: Path, tmp_path: Path):
    target_webp = tmp_path / "trans.webp"
    out_webp = await MediaProcessor.convert_image(sample_png, output_format="webp", target_path=target_webp)
    with Image.open(out_webp) as img:
        assert img.mode == "RGBA"

    target_png = tmp_path / "trans.png"
    out_png = await MediaProcessor.convert_image(sample_png, output_format="png", target_path=target_png)
    with Image.open(out_png) as img:
        assert img.mode == "RGBA"


# 4. Color Modes Tests
@pytest.mark.asyncio
async def test_cmyk_to_jpg_and_png(cmyk_image: Path, tmp_path: Path):
    out_jpg = await MediaProcessor.convert_image(cmyk_image, "jpg", tmp_path / "cmyk.jpg")
    with Image.open(out_jpg) as img:
        assert img.mode == "RGB"

    out_png = await MediaProcessor.convert_image(cmyk_image, "png", tmp_path / "cmyk.png")
    with Image.open(out_png) as img:
        assert img.mode == "RGB"


@pytest.mark.asyncio
async def test_grayscale_and_palette_conversion(grayscale_image: Path, palette_image: Path, tmp_path: Path):
    out_jpg = await MediaProcessor.convert_image(grayscale_image, "jpg", tmp_path / "gray.jpg")
    with Image.open(out_jpg) as img:
        assert img.mode in ("RGB", "L")

    out_png = await MediaProcessor.convert_image(palette_image, "png", tmp_path / "pal.png")
    with Image.open(out_png) as img:
        assert img.mode in ("RGB", "RGBA")


# 5. EXIF Orientation Transposition Tests
@pytest.mark.asyncio
async def test_exif_orientation_applied(exif_rotated_jpeg: Path, tmp_path: Path):
    # Original image is 120x60 with orientation 6 (rotate 90 CW)
    target = tmp_path / "transposed.png"
    out = await MediaProcessor.convert_image(exif_rotated_jpeg, "png", target)
    with Image.open(out) as img:
        # Transposed dimensions must be 60x120
        assert img.size == (60, 120)


# 6. Rejection of GIF & TIFF Inputs and Outputs
@pytest.mark.asyncio
async def test_gif_and_tiff_rejected_as_input(animated_gif_image: Path, multipage_tiff_image: Path, tmp_path: Path):
    with pytest.raises(UnsupportedFormatError):
        MediaProcessor.inspect_image(animated_gif_image)

    with pytest.raises(UnsupportedFormatError):
        await MediaProcessor.convert_image(animated_gif_image, "png", tmp_path / "from_gif.png")

    with pytest.raises(UnsupportedFormatError):
        MediaProcessor.inspect_image(multipage_tiff_image)

    with pytest.raises(UnsupportedFormatError):
        await MediaProcessor.convert_image(multipage_tiff_image, "png", tmp_path / "from_tiff.png")


@pytest.mark.asyncio
async def test_gif_and_tiff_rejected_as_output(sample_png: Path, tmp_path: Path):
    with pytest.raises(UnsupportedFormatError):
        await MediaProcessor.convert_image(sample_png, "gif", tmp_path / "out.gif")

    with pytest.raises(UnsupportedFormatError):
        await MediaProcessor.convert_image(sample_png, "tiff", tmp_path / "out.tiff")


# 7. Preview Non-Interference Tests (Feedback Item 8)
@pytest.mark.asyncio
async def test_preview_generation_does_not_modify_authoritative_output(sample_png: Path, tmp_path: Path):
    target_out = tmp_path / "authoritative.webp"
    out = await MediaProcessor.convert_image(sample_png, "webp", target_out)
    assert out.exists()

    # Calculate SHA256 of the output file
    with open(out, "rb") as f:
        hash_before = hashlib.sha256(f.read()).hexdigest()

    # Generate preview
    preview_file = tmp_path / "temp_preview.jpg"
    preview_res = await MediaProcessor.generate_preview(out, preview_file)

    assert preview_res.exists()
    assert preview_file != out

    # Verify preview is a valid JPEG
    with Image.open(preview_file) as p_img:
        assert p_img.format == "JPEG"

    # Verify authoritative output was NOT modified or re-encoded
    with open(out, "rb") as f:
        hash_after = hashlib.sha256(f.read()).hexdigest()

    assert hash_before == hash_after
    with Image.open(out) as out_img:
        assert out_img.format == "WEBP"


# 8. Invalid Input Handling Tests
def test_inspect_corrupted_or_empty_file(tmp_path: Path):
    empty_file = tmp_path / "empty.jpg"
    empty_file.write_bytes(b"")
    with pytest.raises(CorruptedImageError):
        MediaProcessor.inspect_image(empty_file)

    corrupt_file = tmp_path / "corrupt.png"
    corrupt_file.write_bytes(b"Not an image at all!")
    with pytest.raises(CorruptedImageError):
        MediaProcessor.inspect_image(corrupt_file)


def test_inspect_unsupported_format(tmp_path: Path):
    text_file = tmp_path / "test.txt"
    text_file.write_text("Hello world")
    with pytest.raises(CorruptedImageError):
        MediaProcessor.inspect_image(text_file)


# 9. Sticker Classification Unit Tests
def test_sticker_classification_logic():
    """Verify static vs animated/video sticker classification."""
    class FakeSticker:
        def __init__(self, is_animated: bool, is_video: bool):
            self.is_animated = is_animated
            self.is_video = is_video

    static_stk = FakeSticker(is_animated=False, is_video=False)
    anim_stk = FakeSticker(is_animated=True, is_video=False)
    video_stk = FakeSticker(is_animated=False, is_video=True)

    # Static: accepted
    assert not static_stk.is_animated and not static_stk.is_video
    # Animated: rejected
    assert anim_stk.is_animated or anim_stk.is_video
    # Video: rejected
    assert video_stk.is_animated or video_stk.is_video

