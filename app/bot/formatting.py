"""Telegram message text formatters for metadata and technical info."""

from typing import Optional
from app.audio.models import AudioMetadata, AudioTechnicalInfo


def val_or_dash(val: Optional[str]) -> str:
    if val is None or str(val).strip() == "":
        return "—"
    return str(val).strip()


def format_metadata_preview(
    filename: str,
    metadata: AudioMetadata,
    tech_info: Optional[AudioTechnicalInfo] = None,
) -> str:
    """Format the primary metadata preview message."""
    # Track formatting
    track_str = "—"
    if metadata.track_number is not None:
        track_str = f"{metadata.track_number:02d}"
        if metadata.track_total is not None:
            track_str += f" / {metadata.track_total:02d}"

    # Cover formatting
    cover_str = "—"
    if metadata.has_cover:
        if metadata.cover_dimensions:
            w, h = metadata.cover_dimensions
            cover_str = f"✅ {w}×{h}"
        else:
            cover_str = "✅ Embedded"

    # Lyrics formatting
    has_lyrics = metadata.has_lyrics or bool(metadata.lyrics and str(metadata.lyrics).strip())
    lyrics_str = "✅ Present" if has_lyrics else "—"

    album_artist_line = ""
    if metadata.albumartist:
        album_artist_line = f"<b>Album Artist:</b> {metadata.albumartist}\n"

    comment_line = ""
    if metadata.comment and str(metadata.comment).strip():
        comment_line = f"<b>Comment:</b> {str(metadata.comment).strip()}\n"

    audio_line = ""
    if tech_info:
        parts = [tech_info.format_name]
        if tech_info.bitrate_kbps:
            parts.append(f"{tech_info.bitrate_kbps} kbps")
        if tech_info.sample_rate_hz:
            parts.append(f"{tech_info.sample_rate_hz / 1000:.1f} kHz")
        if tech_info.channel_layout:
            parts.append(tech_info.channel_layout)

        line1 = " • ".join(parts)
        line2 = f"{tech_info.duration_formatted} • {tech_info.file_size_mb} MB"
        audio_line = f"\n\n<b>Audio:</b> {line1}\n{line2}"

    msg = (
        f"🎵 <b>Audio Metadata</b>\n\n"
        f"<b>File:</b> <code>{filename}</code>\n"
        f"<b>Title:</b> {val_or_dash(metadata.title)}\n"
        f"<b>Artist:</b> {val_or_dash(metadata.artist)}\n"
        f"<b>Album:</b> {val_or_dash(metadata.album)}\n"
        f"{album_artist_line}"
        f"<b>Year:</b> {val_or_dash(metadata.date)}\n"
        f"<b>Genre:</b> {val_or_dash(metadata.genre)}\n"
        f"<b>Track:</b> {track_str}\n"
        f"{comment_line}"
        f"<b>Cover:</b> {cover_str}\n"
        f"<b>Lyrics:</b> {lyrics_str}"
        f"{audio_line}"
    )
    return msg


def format_technical_info(
    filename: str,
    tech_info: AudioTechnicalInfo,
) -> str:
    """Format the detailed file information view."""
    cover_str = "—"
    if tech_info.has_cover:
        if tech_info.cover_dimensions:
            w, h = tech_info.cover_dimensions
            cover_str = f"✅ {w}×{h}"
        else:
            cover_str = "✅ Embedded"

    lyrics_str = "✅ Present" if tech_info.has_lyrics else "—"
    bit_depth_str = f"{tech_info.bit_depth}-bit" if tech_info.bit_depth else "—"
    sample_rate_str = (
        f"{tech_info.sample_rate_hz / 1000:.1f} kHz"
        if tech_info.sample_rate_hz
        else "—"
    )
    bitrate_str = (
        f"{tech_info.bitrate_kbps} kbps"
        if tech_info.bitrate_kbps
        else "—"
    )

    return (
        f"📄 <b>File Information</b>\n\n"
        f"<b>Filename:</b> <code>{filename}</code>\n"
        f"<b>Format:</b> {tech_info.format_name} ({tech_info.codec_name})\n"
        f"<b>MIME:</b> {tech_info.mime_type}\n"
        f"<b>Bit depth:</b> {bit_depth_str}\n"
        f"<b>Sample rate:</b> {sample_rate_str}\n"
        f"<b>Bitrate:</b> {bitrate_str}\n"
        f"<b>Channels:</b> {tech_info.channel_layout or '—'}\n"
        f"<b>Duration:</b> {tech_info.duration_formatted}\n"
        f"<b>Size:</b> {tech_info.file_size_mb} MB\n"
        f"<b>Tags:</b> {tech_info.tag_type}\n"
        f"<b>Cover:</b> {cover_str}\n"
        f"<b>Lyrics:</b> {lyrics_str}"
    )
