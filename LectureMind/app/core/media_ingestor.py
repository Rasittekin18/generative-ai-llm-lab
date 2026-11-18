"""YouTube ve diğer web sitelerinden veya yerel dosyalardan ses çıkarma modülü."""

from dataclasses import dataclass, field
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import parse_qs, urlparse

import yt_dlp


YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass
class IngestedMedia:
    """İndirilmiş veya hazırlanmış medya bilgisi."""

    lecture_id: str
    title: str
    audio_path: Path
    duration_sec: float
    platform: str
    source_url: str | None = None
    youtube_id: str | None = None
    source_chapters: list[dict[str, Any]] = field(default_factory=list)


def extract_youtube_id(url: str | None) -> str | None:
    """YouTube URL'sinden 11 karakterlik video kimliğini çıkarır."""
    if not url:
        return None
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if "youtu.be" in host:
        candidate = parsed.path.lstrip("/").split("/")[0]
        return candidate if YOUTUBE_ID_RE.match(candidate) else None
    if "youtube.com" in host or "youtube-nocookie.com" in host:
        qs = parse_qs(parsed.query)
        if "v" in qs and YOUTUBE_ID_RE.match(qs["v"][0]):
            return qs["v"][0]
        parts = [p for p in parsed.path.split("/") if p]
        for prefix in ("embed", "shorts", "live", "v"):
            if prefix in parts:
                idx = parts.index(prefix)
                if idx + 1 < len(parts) and YOUTUBE_ID_RE.match(parts[idx + 1]):
                    return parts[idx + 1]
    return None


def _run_ffmpeg_to_mp3(src_path: Path, dst_path: Path) -> float:
    """Herhangi bir ses/video dosyasını 16kHz mono MP3'e dönüştürür ve süresini döndürür."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "64k",
        str(dst_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not dst_path.exists():
        raise RuntimeError(f"FFmpeg dönüştürme hatası: {proc.stderr[-400:]}")
    return _probe_duration(dst_path)


def _probe_duration(media_path: Path) -> float:
    """FFprobe ile medya süresini saniye cinsinden ölçer."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode == 0 and proc.stdout.strip():
        try:
            return float(proc.stdout.strip())
        except ValueError:
            pass
    return 0.0


def ingest_url(url: str, lecture_id: str, media_dir: Path) -> IngestedMedia:
    """YouTube veya yt-dlp tarafından desteklenen herhangi bir siteden ses indirir."""
    target_dir = media_dir / lecture_id
    target_dir.mkdir(parents=True, exist_ok=True)
    raw_template = str(target_dir / "source.%(ext)s")

    ydl_opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": raw_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "64",
            }
        ],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise RuntimeError(
            "Bağlantıdan medya indirilemedi. Sitenin herkese açık olduğundan veya "
            f"geçerli bir medya bağlantısı olduğundan emin olun. Ayrıntı: {exc}"
        ) from exc

    if not info:
        raise RuntimeError("Bağlantıdan medya bilgisi alınamadı.")

    if "entries" in info and info["entries"]:
        info = info["entries"][0]

    mp3_path = target_dir / "source.mp3"
    if not mp3_path.exists():
        candidates = sorted(target_dir.glob("source.*"))
        if not candidates:
            raise RuntimeError("İndirilen ses dosyası bulunamadı.")
        _run_ffmpeg_to_mp3(candidates[0], mp3_path)

    final_audio = target_dir / "audio.mp3"
    if final_audio.exists():
        final_audio.unlink()
    duration = _run_ffmpeg_to_mp3(mp3_path, final_audio)
    if mp3_path.exists():
        mp3_path.unlink()

    if not duration:
        duration = float(info.get("duration") or 0.0)

    yt_id = extract_youtube_id(url) or (
        info.get("id") if "youtube" in (info.get("extractor_key") or "").lower() else None
    )
    platform = (info.get("extractor_key") or info.get("extractor") or "web").lower()
    raw_chapters = info.get("chapters") or []
    chapters = [
        {
            "title": ch.get("title") or f"Bölüm {i + 1}",
            "start_sec": float(ch.get("start_time") or 0.0),
            "end_sec": float(ch.get("end_time") or 0.0),
        }
        for i, ch in enumerate(raw_chapters)
    ]

    return IngestedMedia(
        lecture_id=lecture_id,
        title=str(info.get("title") or "Adsız Ders Kaydı"),
        audio_path=final_audio,
        duration_sec=duration,
        platform=platform,
        source_url=url,
        youtube_id=yt_id,
        source_chapters=chapters,
    )


def ingest_local_file(
    uploaded_path: Path,
    original_filename: str,
    lecture_id: str,
    media_dir: Path,
) -> IngestedMedia:
    """Yerel ses veya video dosyasını 16kHz mono MP3'e dönüştürüp hazırlar."""
    target_dir = media_dir / lecture_id
    target_dir.mkdir(parents=True, exist_ok=True)
    final_audio = target_dir / "audio.mp3"
    duration = _run_ffmpeg_to_mp3(uploaded_path, final_audio)

    title = Path(original_filename).stem.replace("_", " ").replace("-", " ").strip()
    return IngestedMedia(
        lecture_id=lecture_id,
        title=title or "Yüklenen Kayıt",
        audio_path=final_audio,
        duration_sec=duration,
        platform="upload",
        source_url=None,
        youtube_id=None,
        source_chapters=[],
    )
