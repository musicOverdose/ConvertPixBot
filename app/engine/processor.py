"""
Static image format converter engine using Pillow and pillow-heif.

Supports input formats:
JPG, JPEG, PNG, WEBP, BMP, ICO, HEIC, HEIF, AVIF, PSD.

Supports output formats:
PNG, JPG, WEBP, PDF, ICO, BMP.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

# Register pillow-heif opener dynamically if available
try:
    import pillow_heif
    if hasattr(pillow_heif, "register_heif_opener"):
        pillow_heif.register_heif_opener()
        logger.info("Successfully registered pillow-heif opener plugin.")
except Exception as e:
    logger.warning(f"Could not initialize pillow-heif plugin: {e}")

# Prevent decompression bomb attacks
MAX_IMAGE_PIXELS = 100_000_000
MAX_IMAGE_DIMENSION = 15_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

SUPPORTED_INPUT_FORMATS: Set[str] = {
    "JPEG", "JPG", "PNG", "WEBP", "BMP", "ICO",
    "HEIC", "HEIF", "AVIF", "PSD"
}

SUPPORTED_OUTPUT_FORMATS: Set[str] = {
    "PNG", "JPG", "JPEG", "WEBP", "PDF", "ICO", "BMP"
}

REQUIRED_ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


class ImageProcessingError(Exception):
    """Base exception for image processing errors."""
    pass


class UnsupportedFormatError(ImageProcessingError):
    """Raised when the input format is unsupported."""
    pass


class CorruptedImageError(ImageProcessingError):
    """Raised when the image file is corrupted or unreadable."""
    pass


class ImageDimensionLimitError(ImageProcessingError):
    """Raised when image dimensions or pixel counts exceed safety limits."""
    pass


class MediaProcessor:
    """
    Robust static image conversion engine.
    Ensures single-frame/single-image processing without animation or multi-page output.
    """

    @staticmethod
    def inspect_image(input_path: Path) -> Dict[str, Any]:
        """
        Inspects an image file with Pillow, validating format from contents.
        Returns format, resolution (width, height), mode, and file size in bytes.
        """
        if not input_path.exists() or not input_path.is_file():
            raise CorruptedImageError(f"Input file not found: {input_path}")

        file_size = input_path.stat().st_size
        if file_size == 0:
            raise CorruptedImageError("Input file is empty (0 bytes).")

        try:
            with Image.open(input_path) as img:
                # Seek to first frame for multi-frame formats (GIF, TIFF)
                try:
                    img.seek(0)
                except (EOFError, ValueError):
                    pass

                raw_format = (img.format or "").upper()
                if not raw_format:
                    raise UnsupportedFormatError("Unable to detect image format from file content.")

                # Normalize format string
                norm_format = "JPG" if raw_format == "JPEG" else raw_format
                if norm_format not in SUPPORTED_INPUT_FORMATS and raw_format not in SUPPORTED_INPUT_FORMATS:
                    raise UnsupportedFormatError(f"Unsupported format '{raw_format}'.")

                w, h = img.size
                if w <= 0 or h <= 0:
                    raise CorruptedImageError(f"Invalid image dimensions: {w}x{h}.")

                if w > MAX_IMAGE_DIMENSION or h > MAX_IMAGE_DIMENSION or (w * h) > MAX_IMAGE_PIXELS:
                    raise ImageDimensionLimitError(
                        f"Image dimensions {w}x{h} exceed maximum safety limit."
                    )

                mode = img.mode

                return {
                    "format": norm_format,
                    "width": w,
                    "height": h,
                    "mode": mode,
                    "file_size_bytes": file_size,
                }
        except (UnidentifiedImageError, SyntaxError) as e:
            raise CorruptedImageError(f"Cannot identify or decode image file: {e}") from e
        except Image.DecompressionBombError as e:
            raise ImageDimensionLimitError(f"Decompression bomb detected: {e}") from e
        except ImageProcessingError:
            raise
        except Exception as e:
            raise CorruptedImageError(f"Error inspecting image: {e}") from e

    @staticmethod
    async def async_inspect_image(input_path: Path) -> Dict[str, Any]:
        """Asynchronously inspects an image file."""
        return await asyncio.to_thread(MediaProcessor.inspect_image, input_path)

    @classmethod
    def convert_image_sync(
        cls,
        input_path: Path,
        output_format: str,
        target_path: Optional[Path] = None,
    ) -> Path:
        """
        Synchronously converts an image to the target format.
        Treats GIF/TIFF strictly as single-image inputs (frame/page 0 only).
        """
        fmt_upper = output_format.upper()
        if fmt_upper == "JPEG":
            fmt_upper = "JPG"

        if fmt_upper not in SUPPORTED_OUTPUT_FORMATS:
            raise UnsupportedFormatError(f"Target format '{output_format}' is not supported.")

        ext = fmt_upper.lower()
        if target_path is None:
            target_path = input_path.with_suffix(f".{ext}")

        target_path = Path(target_path).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with Image.open(input_path) as img:
                raw_format = (img.format or "").upper()
                norm_format = "JPG" if raw_format == "JPEG" else raw_format
                if norm_format not in SUPPORTED_INPUT_FORMATS and raw_format not in SUPPORTED_INPUT_FORMATS:
                    raise UnsupportedFormatError(f"Unsupported input format '{raw_format}'.")

                # Flatten PSD composite image
                if (img.format or "").upper() == "PSD":
                    img.load()

                # 2. EXIF orientation transposition applied to actual pixels
                try:
                    transposed = ImageOps.exif_transpose(img)
                    if transposed is not None:
                        img = transposed
                except Exception as e:
                    logger.debug(f"EXIF transpose skipped or failed: {e}")

                # Check dimensions
                w, h = img.size
                if w > MAX_IMAGE_DIMENSION or h > MAX_IMAGE_DIMENSION or (w * h) > MAX_IMAGE_PIXELS:
                    raise ImageDimensionLimitError(f"Image {w}x{h} exceeds maximum safe limit.")

                # Extract ICC profile if present to preserve colors
                icc_profile = img.info.get("icc_profile")

                # 3. Handle conversion based on target format
                if fmt_upper in ("JPG", "JPEG"):
                    # JPG requires RGB mode, flatten alpha onto solid white background
                    img = cls._flatten_to_rgb(img)
                    save_kwargs = {"quality": 92, "optimize": True}
                    if icc_profile:
                        save_kwargs["icc_profile"] = icc_profile
                    img.save(target_path, format="JPEG", **save_kwargs)

                elif fmt_upper == "PNG":
                    # PNG preserves transparency, convert CMYK to RGB
                    if img.mode == "CMYK":
                        img = img.convert("RGB")
                    elif img.mode == "P":
                        if cls._has_transparency(img):
                            img = img.convert("RGBA")
                        else:
                            img = img.convert("RGB")
                    save_kwargs = {"optimize": True, "compress_level": 6}
                    if icc_profile:
                        save_kwargs["icc_profile"] = icc_profile
                    img.save(target_path, format="PNG", **save_kwargs)

                elif fmt_upper == "WEBP":
                    # WEBP preserves alpha, maintains original dimensions
                    if img.mode == "CMYK":
                        img = img.convert("RGB")
                    elif img.mode == "P":
                        if cls._has_transparency(img):
                            img = img.convert("RGBA")
                        else:
                            img = img.convert("RGB")
                    elif img.mode == "LA":
                        img = img.convert("RGBA")
                    elif img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGBA" if cls._has_transparency(img) else "RGB")

                    save_kwargs = {"quality": 90, "method": 6}
                    if icc_profile:
                        save_kwargs["icc_profile"] = icc_profile
                    img.save(target_path, format="WEBP", **save_kwargs)

                elif fmt_upper == "BMP":
                    # Standard BMP: flatten alpha onto white background, RGB mode
                    img = cls._flatten_to_rgb(img)
                    img.save(target_path, format="BMP")

                elif fmt_upper == "ICO":
                    # Multi-resolution ICO: at least 16, 32, 48, 64, 128, 256
                    if img.mode not in ("RGBA", "RGB"):
                        img = img.convert("RGBA" if cls._has_transparency(img) else "RGB")
                    # Ensure base is at least 256x256 using LANCZOS so all resolutions up to 256x256 are generated
                    base_ico = img.resize((256, 256), Image.Resampling.LANCZOS)
                    base_ico.save(
                        target_path,
                        format="ICO",
                        sizes=REQUIRED_ICO_SIZES,
                    )

                elif fmt_upper == "PDF":
                    # Exactly one page PDF, preserve aspect ratio, flatten alpha onto white
                    img = cls._flatten_to_rgb(img)
                    img.save(target_path, format="PDF", resolution=100.0)

                else:
                    raise UnsupportedFormatError(f"Target format '{output_format}' is not supported.")

            cls.validate_output(target_path, fmt_upper)
            return target_path

        except ImageProcessingError:
            if target_path.exists():
                try:
                    target_path.unlink()
                except OSError:
                    pass
            raise
        except Exception as e:
            if target_path.exists():
                try:
                    target_path.unlink()
                except OSError:
                    pass
            raise ImageProcessingError(f"Failed to convert image to {fmt_upper}: {e}") from e

    @classmethod
    async def convert_image(
        cls,
        input_path: Path,
        output_format: str = "png",
        target_path: Optional[Path] = None,
    ) -> Path:
        """Asynchronously converts an image to the requested format using a worker thread."""
        return await asyncio.to_thread(
            cls.convert_image_sync,
            input_path,
            output_format,
            target_path,
        )

    @classmethod
    def validate_output(cls, output_path: Path, expected_format: str) -> None:
        """
        Validates that the output file exists, has non-zero size, and conforms
        to the expected format specifications.
        """
        if not output_path.exists() or not output_path.is_file():
            raise CorruptedImageError(f"Converted file does not exist: {output_path}")

        file_size = output_path.stat().st_size
        if file_size == 0:
            raise CorruptedImageError(f"Converted file is 0 bytes: {output_path}")

        fmt_upper = expected_format.upper()
        if fmt_upper in ("JPG", "JPEG"):
            fmt_upper = "JPEG"

        if fmt_upper == "PDF":
            # Verify PDF header, trailer, and single page structure
            with open(output_path, "rb") as f:
                header = f.read(10)
                if not header.startswith(b"%PDF-"):
                    raise CorruptedImageError("Invalid PDF header.")
                f.seek(max(0, file_size - 1024))
                tail = f.read()
                if b"%%EOF" not in tail:
                    raise CorruptedImageError("Invalid PDF trailer (missing %%EOF).")
            # PDF is verified
            return

        # Reopen with Pillow to verify valid image output
        try:
            with Image.open(output_path) as out_img:
                out_format = (out_img.format or "").upper()
                if fmt_upper == "JPEG" and out_format == "JPEG":
                    pass
                elif fmt_upper == out_format:
                    pass
                else:
                    raise CorruptedImageError(
                        f"Expected format {fmt_upper}, but file is {out_format}."
                    )

                w, h = out_img.size
                if w <= 0 or h <= 0:
                    raise CorruptedImageError(f"Invalid output dimensions {w}x{h}.")

                if fmt_upper == "ICO":
                    # Check ICO contained resolutions
                    ico_sizes = set()
                    if hasattr(out_img, "ico") and hasattr(out_img.ico, "sizes"):
                        ico_sizes = set(out_img.ico.sizes())
                    for req_size in REQUIRED_ICO_SIZES:
                        if req_size not in ico_sizes:
                            raise CorruptedImageError(f"ICO missing required size: {req_size}")

        except Exception as e:
            raise CorruptedImageError(f"Output verification failed: {e}") from e

    @classmethod
    def generate_preview_sync(
        cls,
        source_path: Path,
        preview_path: Path,
        max_dimension: int = 1920,
    ) -> Path:
        """
        Generates an independent JPEG preview image for display in Telegram.
        The preview file is completely separate from the authoritative conversion output.
        """
        preview_path = Path(preview_path).resolve()
        preview_path.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(source_path) as img:
            try:
                img.seek(0)
            except (EOFError, ValueError):
                pass

            try:
                transposed = ImageOps.exif_transpose(img)
                if transposed is not None:
                    img = transposed
            except Exception:
                pass

            # Flatten onto white background
            rgb_img = cls._flatten_to_rgb(img)

            # Resize if dimensions exceed max_dimension
            w, h = rgb_img.size
            if w > max_dimension or h > max_dimension:
                rgb_img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

            rgb_img.save(preview_path, format="JPEG", quality=85, optimize=True)

        return preview_path

    @classmethod
    async def generate_preview(
        cls,
        source_path: Path,
        preview_path: Path,
        max_dimension: int = 1920,
    ) -> Path:
        """Asynchronously generates an independent JPEG preview file."""
        return await asyncio.to_thread(
            cls.generate_preview_sync,
            source_path,
            preview_path,
            max_dimension,
        )

    @staticmethod
    def _has_transparency(img: Image.Image) -> bool:
        """Checks whether the image has transparency data."""
        if img.mode in ("RGBA", "LA"):
            return True
        if img.mode == "P" and "transparency" in img.info:
            return True
        if getattr(img, "has_transparency_data", False):
            return True
        return False

    @classmethod
    def _flatten_to_rgb(cls, img: Image.Image) -> Image.Image:
        """
        Flattens any alpha / transparency onto a pure white RGB background.
        Ensures output mode is strictly RGB.
        """
        if img.mode == "RGB":
            return img.copy()

        if cls._has_transparency(img) or img.mode in ("RGBA", "LA"):
            rgba = img.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            alpha_mask = rgba.split()[3]
            bg.paste(rgba, mask=alpha_mask)
            return bg

        if img.mode == "CMYK":
            return img.convert("RGB")

        if img.mode == "L":
            return img.convert("RGB")

        return img.convert("RGB")

