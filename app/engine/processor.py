"""Example domain engine processor (e.g. Image Format Converter / Media Processor)."""

import asyncio
from pathlib import Path
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class MediaProcessor:
    """
    Generic media processor.
    In an Image Format Converter bot, this handles conversions between PNG, JPEG, WEBP, etc.
    """

    @staticmethod
    async def convert_image(
        input_path: Path,
        output_format: str = 'png',
        target_path: Path | None = None,
    ) -> Path:
        """Asynchronously converts an image to the requested format using Pillow."""
        if target_path is None:
            target_path = input_path.with_suffix(f'.{output_format.lower()}')

        def _do_convert():
            with Image.open(input_path) as img:
                # Convert RGBA to RGB if saving to JPEG
                if output_format.lower() in ('jpg', 'jpeg') and img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                img.save(target_path, format=output_format.upper())
            return target_path

        return await asyncio.to_thread(_do_convert)
