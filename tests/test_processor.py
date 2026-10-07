"""Tests for MediaProcessor domain conversion."""

from pathlib import Path
import pytest
from PIL import Image
from app.engine.processor import MediaProcessor


@pytest.mark.asyncio
async def test_image_conversion_jpeg_to_png(sample_jpeg: Path, tmp_path: Path):
    target = tmp_path / 'out.png'
    out = await MediaProcessor.convert_image(sample_jpeg, output_format='png', target_path=target)
    assert out.exists()
    with Image.open(out) as img:
        assert img.format == 'PNG'


@pytest.mark.asyncio
async def test_image_conversion_png_to_jpeg(sample_png: Path, tmp_path: Path):
    target = tmp_path / 'out.jpg'
    out = await MediaProcessor.convert_image(sample_png, output_format='jpeg', target_path=target)
    assert out.exists()
    with Image.open(out) as img:
        assert img.format == 'JPEG'
