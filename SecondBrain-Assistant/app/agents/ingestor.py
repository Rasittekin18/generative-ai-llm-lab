from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from app.schemas import ChannelVideoItem, IngestedContent

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "music.youtube.com",
}


def extract_youtube_id(url: str) -> Optional[str]:
    """YouTube URL'lerinden 11 karakterlik video ID'sini çıkarır."""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if host not in YOUTUBE_HOSTS:
        return None

    if "youtu.be" in host:
        vid = parsed.path.lstrip("/").split("/")[0]
        return vid if len(vid) == 11 else None

    if parsed.path == "/watch":
        qs = parse_qs(parsed.query)
        vid = qs.get("v", [""])[0]
        return vid if len(vid) == 11 else None

    for prefix in ("/shorts/", "/embed/", "/live/", "/v/"):
        if parsed.path.startswith(prefix):
            vid = parsed.path[len(prefix) :].split("/")[0]
            return vid if len(vid) == 11 else None

    return None


def is_youtube_url(url: str) -> bool:
    return extract_youtube_id(url) is not None


def _snippet_text(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("text", "")).strip()
    return str(getattr(item, "text", "")).strip()


def _fetch_youtube_transcript_sync(video_id: str) -> tuple[str, Optional[str]]:
    """youtube-transcript-api v1.x ve v0.6 sürümleriyle uyumlu altyazı çıkarıcı."""
    from youtube_transcript_api import YouTubeTranscriptApi

    preferred_langs = ["tr", "en", "en-US", "en-GB"]

    # v1.x API (YouTubeTranscriptApi().list / .fetch)
    if hasattr(YouTubeTranscriptApi, "list") and callable(
        getattr(YouTubeTranscriptApi, "list")
    ):
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
    else:
        # v0.6 legacy API
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

    chosen = None
    for getter_name in ("find_manually_created_transcript", "find_generated_transcript", "find_transcript"):
        getter = getattr(transcript_list, getter_name, None)
        if getter is None:
            continue
        try:
            chosen = getter(preferred_langs)
            break
        except Exception:
            continue

    if chosen is None:
        for tr in transcript_list:
            chosen = tr
            break

    if chosen is None:
        raise ValueError("Bu YouTube videosu için uygun bir altyazı bulunamadı.")

    fetched = chosen.fetch()
    lines = [_snippet_text(part) for part in fetched]
    cleaned = " ".join(line for line in lines if line)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        raise ValueError("Video altyazısı boş döndü.")
    return cleaned, getattr(chosen, "language_code", None)


def _fetch_youtube_metadata_sync(url: str, video_id: str) -> dict[str, object]:
    """yt-dlp ile video başlığı, kanal adı, süre ve küçük resmi alır."""
    try:
        import yt_dlp

        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                return {
                    "title": info.get("title") or f"YouTube Video ({video_id})",
                    "author": info.get("uploader") or info.get("channel"),
                    "duration_seconds": info.get("duration"),
                    "thumbnail_url": info.get("thumbnail")
                    or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                }
    except Exception:
        pass

    return {
        "title": f"YouTube Video ({video_id})",
        "author": None,
        "duration_seconds": None,
        "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    }


async def _fetch_youtube_oembed(url: str) -> dict[str, Optional[str]]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "title": data.get("title"),
                    "author": data.get("author_name"),
                    "thumbnail_url": data.get("thumbnail_url"),
                }
    except Exception:
        pass
    return {}


class IngestorAgent:
    """1. Ajan: YouTube videoları, web makaleleri ve düz metinlerden ham içeriği toplar."""

    async def ingest(
        self,
        url: Optional[str] = None,
        text: Optional[str] = None,
        title: Optional[str] = None,
    ) -> IngestedContent:
        if text and text.strip():
            raw = text.strip()
            inferred_title = (
                title.strip()
                if title and title.strip()
                else raw.splitlines()[0][:80].strip() or "Metin Notu"
            )
            return IngestedContent(
                source_type="text",
                source_url=None,
                title=inferred_title,
                author="Kişisel Not",
                raw_text=raw,
                language="tr",
            )

        if not url or not url.strip():
            raise ValueError("Özetlemek için geçerli bir URL veya metin girmelisiniz.")

        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "https://" + clean_url

        video_id = extract_youtube_id(clean_url)
        if video_id:
            return await self.ingest_youtube(clean_url, video_id)
        return await self.ingest_article(clean_url, override_title=title)

    async def ingest_youtube(self, url: str, video_id: str) -> IngestedContent:
        meta_task = asyncio.to_thread(_fetch_youtube_metadata_sync, url, video_id)
        oembed_task = _fetch_youtube_oembed(url)

        try:
            transcript_text, lang = await asyncio.to_thread(
                _fetch_youtube_transcript_sync, video_id
            )
        except Exception as exc:
            raise ValueError(
                f"YouTube video altyazısı alınamadı ({exc}). "
                "Videonun altyazısı kapalı veya erişime kısıtlı olabilir."
            ) from exc

        meta, oembed = await asyncio.gather(meta_task, oembed_task)
        resolved_title = str(
            oembed.get("title") or meta.get("title") or f"YouTube Video ({video_id})"
        )
        if resolved_title.startswith("YouTube Video (") and oembed.get("title"):
            resolved_title = str(oembed["title"])

        author = meta.get("author") or oembed.get("author")
        thumb = meta.get("thumbnail_url") or oembed.get("thumbnail_url")
        duration = meta.get("duration_seconds")

        return IngestedContent(
            source_type="youtube",
            source_url=f"https://www.youtube.com/watch?v={video_id}",
            title=resolved_title,
            author=str(author) if author else None,
            raw_text=transcript_text,
            thumbnail_url=str(thumb) if thumb else None,
            duration_seconds=int(duration) if isinstance(duration, (int, float)) else None,
            language=lang,
        )

    async def ingest_article(
        self, url: str, override_title: Optional[str] = None
    ) -> IngestedContent:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=20.0, headers=DEFAULT_HEADERS
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        import trafilatura

        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            output_format="txt",
        )
        metadata = trafilatura.extract_metadata(html)

        soup = BeautifulSoup(html, "html.parser")
        page_title = (
            override_title
            or (metadata.title if metadata and metadata.title else None)
            or (soup.title.string.strip() if soup.title and soup.title.string else None)
            or urlparse(url).netloc
        )
        author = metadata.author if metadata and metadata.author else urlparse(url).netloc

        if not extracted or len(extracted.strip()) < 120:
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all(["p", "li", "h1", "h2", "h3"])]
            extracted = "\n".join(p for p in paragraphs if len(p) > 25)

        if not extracted or len(extracted.strip()) < 80:
            raise ValueError(
                "Web sayfasından anlamlı makale metni çıkarılamadı. "
                "Sayfa JavaScript ile yükleniyor veya bot koruması içeriyor olabilir."
            )

        return IngestedContent(
            source_type="article",
            source_url=str(resp.url),
            title=page_title.strip(),
            author=author,
            raw_text=extracted.strip(),
        )

    async def resolve_youtube_channel(self, url_or_id: str) -> tuple[str, str]:
        """Kanal @handle, URL veya UC... ID'sini çözümleyip (channel_id, title) döndürür."""
        raw = url_or_id.strip()
        if re.fullmatch(r"UC[a-zA-Z0-9_-]{22}", raw):
            videos = await self.fetch_channel_videos(raw, limit=1)
            return raw, (videos[0][1] if videos else raw)

        if raw.startswith("@"):
            target_url = f"https://www.youtube.com/{raw}"
        elif raw.startswith(("http://", "https://")):
            target_url = raw
        else:
            target_url = f"https://www.youtube.com/@{raw.lstrip('@')}"

        async with httpx.AsyncClient(
            follow_redirects=True, timeout=15.0, headers=DEFAULT_HEADERS
        ) as client:
            resp = await client.get(target_url)
            resp.raise_for_status()
            html = resp.text

        channel_id = None
        m = re.search(
            r'<link[^>]+rel="canonical"[^>]+href="https://www\.youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})"',
            html,
        )
        if m:
            channel_id = m.group(1)
        if not channel_id:
            m2 = re.search(r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"', html)
            if m2:
                channel_id = m2.group(1)

        if not channel_id:
            raise ValueError("YouTube kanal kimliği (channel_id) çözümlenemedi.")

        title_match = re.search(r"<title>(.*?)</title>", html, re.S)
        ch_title = (
            title_match.group(1).replace(" - YouTube", "").strip()
            if title_match
            else raw
        )
        return channel_id, ch_title

    async def fetch_channel_videos(
        self, channel_id: str, limit: int = 8
    ) -> list[tuple[ChannelVideoItem, str]]:
        """Ücretsiz YouTube RSS akışından son videoları çeker."""
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        async with httpx.AsyncClient(timeout=15.0, headers=DEFAULT_HEADERS) as client:
            resp = await client.get(rss_url)
            resp.raise_for_status()
        return parse_youtube_rss(resp.text, limit=limit)


def parse_youtube_rss(xml_text: str, limit: int = 8) -> list[tuple[ChannelVideoItem, str]]:
    """YouTube RSS Atom XML çıktısını ayrıştırır."""
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }
    root = ET.fromstring(xml_text)
    channel_title_el = root.find("atom:title", ns)
    channel_title = channel_title_el.text.strip() if channel_title_el is not None and channel_title_el.text else "YouTube Kanalı"

    items: list[tuple[ChannelVideoItem, str]] = []
    for entry in root.findall("atom:entry", ns)[:limit]:
        vid_el = entry.find("yt:videoId", ns)
        title_el = entry.find("atom:title", ns)
        pub_el = entry.find("atom:published", ns)
        thumb_el = entry.find("media:group/media:thumbnail", ns)

        if vid_el is None or not vid_el.text:
            continue
        vid = vid_el.text.strip()
        vtitle = title_el.text.strip() if title_el is not None and title_el.text else vid
        published = pub_el.text.strip() if pub_el is not None and pub_el.text else ""
        thumb = (
            thumb_el.attrib.get("url")
            if thumb_el is not None
            else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        )

        items.append(
            (
                ChannelVideoItem(
                    video_id=vid,
                    title=vtitle,
                    url=f"https://www.youtube.com/watch?v={vid}",
                    published_at=published,
                    thumbnail_url=thumb,
                ),
                channel_title,
            )
        )
    return items
