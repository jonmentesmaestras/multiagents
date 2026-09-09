"""Official YouTube Data API v3 tool with automatic Playwright fallback for video search and comments collection."""

import datetime
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional, Union
from dotenv import find_dotenv, load_dotenv

from .youtube_search_tool import search_youtube_videos

logger = logging.getLogger(__name__)


def _get_api_key() -> str:
    """Retrieves the YouTube API key from environment variables."""
    load_dotenv(find_dotenv(), override=False)
    return (
        os.environ.get("YOUTUBE_API_KEY", "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
    )


def format_view_count(views: int) -> str:
    """Formats an integer view count to a human-readable string (e.g., 450K, 1.2M)."""
    if views >= 1_000_000_000:
        val = views / 1_000_000_000
        return f"{val:.1f}B".replace(".0B", "B")
    elif views >= 1_000_000:
        val = views / 1_000_000
        return f"{val:.1f}M".replace(".0M", "M")
    elif views >= 1_000:
        val = views / 1_000
        return f"{val:.0f}K" if val.is_integer() else f"{val:.1f}K".replace(".0K", "K")
    return str(views)


def extract_video_id(video_id_or_url: str) -> str:
    """Extracts YouTube video ID from a URL or returns the ID directly."""
    if not video_id_or_url:
        return ""
    clean = video_id_or_url.strip()
    if len(clean) == 11 and not ("/" in clean or "?" in clean or "=" in clean):
        return clean
    match = re.search(r"(?:v=|\/embed\/|youtu\.be\/|\/v\/|\/watch\?v=|\&v=)([\w-]+)", clean)
    if match:
        return match.group(1)
    if not clean.startswith("http://") and not clean.startswith("https://"):
        return clean
    return ""


def search_youtube_videos_api(
    keywords: Union[list[str], str],
    min_views: int = 0,
    max_results_per_keyword: int = 50,
    api_key: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Searches YouTube videos using official YouTube Data API v3.

    Args:
        keywords: A single keyword string or list of keyword strings.
        min_views: Optional minimum view count. Defaults to zero; relevance is decided later.
        max_results_per_keyword: Maximum videos to collect per keyword (up to 50).
        api_key: Optional explicit API key. If omitted, uses YOUTUBE_API_KEY from .env.

    Returns:
        A list of dictionaries conforming to the schema:
            [
                {
                    "video_keywords": str,
                    "video_title": str,
                    "video_href": str,
                    "video_views": str
                }
            ]
    """
    key = api_key or _get_api_key()
    if not key:
        raise ValueError("No YouTube API key provided or found in environment variables.")

    if isinstance(keywords, str):
        kw_clean = keywords.strip()
        kw_list = [kw_clean] if kw_clean else []
    elif isinstance(keywords, list):
        kw_list = [k.strip() for k in keywords if isinstance(k, str) and k.strip()]
    else:
        logger.warning(f"Invalid keywords format: {keywords}")
        return []

    if not kw_list:
        return []

    collected_videos: list[dict[str, Any]] = []


    for kw in kw_list:
        try:
            logger.info(f"[YouTube API] Searching videos for keyword: '{kw}' (max={max_results_per_keyword})")
            encoded_query = urllib.parse.quote(kw)
            search_url = (
                f"https://www.googleapis.com/youtube/v3/search"
                f"?part=snippet"
                f"&q={encoded_query}"
                f"&type=video"
                f"&order=relevance"
                f"&relevanceLanguage=es"
                f"&maxResults={max_results_per_keyword}"
                f"&key={key}"
            )

            req = urllib.request.Request(search_url, headers={"User-Agent": "MarketingCampaignAgent/1.0"})
            with urllib.request.urlopen(req, timeout=15) as response:
                search_data = json.loads(response.read().decode("utf-8"))

            items = search_data.get("items", [])
            video_ids = [
                item["id"]["videoId"]
                for item in items
                if isinstance(item.get("id"), dict) and "videoId" in item["id"]
            ]

            if not video_ids:
                logger.info(f"[YouTube API] No video IDs found for keyword: '{kw}'")
                continue

            # Fetch detailed statistics (viewCount, exact title)
            ids_param = ",".join(video_ids)
            videos_url = (
                f"https://www.googleapis.com/youtube/v3/videos"
                f"?part=snippet,statistics"
                f"&id={ids_param}"
                f"&key={key}"
            )

            req_videos = urllib.request.Request(videos_url, headers={"User-Agent": "MarketingCampaignAgent/1.0"})
            with urllib.request.urlopen(req_videos, timeout=15) as response_videos:
                videos_data = json.loads(response_videos.read().decode("utf-8"))

            kw_collected = 0
            for vid_item in videos_data.get("items", []):
                if kw_collected >= max_results_per_keyword:
                    break

                vid_id = vid_item["id"]
                snippet = vid_item.get("snippet", {})
                statistics = vid_item.get("statistics", {})

                title = snippet.get("title", "").strip()
                raw_views = statistics.get("viewCount", "0")
                try:
                    view_count = int(raw_views)
                except (ValueError, TypeError):
                    view_count = 0

                # Filter by minimum views
                if view_count < min_views:
                    logger.info(
                        f"[YouTube API] Skipping video '{title}' - Views ({view_count}) < {min_views}"
                    )
                    continue

                formatted_views = f"{format_view_count(view_count)} views"
                raw_comments = statistics.get("commentCount")
                try:
                    comment_count = int(raw_comments) if raw_comments is not None else None
                except (ValueError, TypeError):
                    comment_count = None
                video_url = f"https://www.youtube.com/watch?v={vid_id}"

                collected_videos.append({
                    "video_keywords": kw,
                    "video_title": title,
                    "video_href": video_url,
                    "video_id": vid_id,
                    "video_views": formatted_views,
                    "view_count": view_count,
                    "comment_count": comment_count,
                    "published_at": snippet.get("publishedAt"),
                    "video_description": snippet.get("description", "").strip()[:500],
                    "channel_title": snippet.get("channelTitle", "").strip(),
                    "default_language": snippet.get("defaultLanguage") or "unknown",
                    "audio_language": snippet.get("defaultAudioLanguage") or "unknown",
                    "search_source": "youtube_api",
                    "metadata_status": "complete",
                })
                kw_collected += 1

        except Exception as e:
            logger.error(f"[YouTube API] Failed search for keyword '{kw}': {e}", exc_info=True)
            raise

    return collected_videos


def collect_youtube_comments_api(
    video_id_or_url: str,
    max_comments: int = 50,
    max_months: int = 6,
    api_key: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Collects comments from a YouTube video using YouTube Data API v3 with relative date filtering (<= 6 months).

    Args:
        video_id_or_url: YouTube video ID or full watch URL.
        max_comments: Maximum comments to collect (default: 50).
        max_months: Maximum age in months (default: 6). Older comments are excluded.
        api_key: Optional API key.

    Returns:
        List of comment objects:
            [
                {
                    "author": str,
                    "text": str,
                    "published_at": str,
                    "like_count": int
                }
            ]
    """
    key = api_key or _get_api_key()
    if not key:
        return []

    video_id = extract_video_id(video_id_or_url)
    if not video_id:
        return []

    collected_comments: list[dict[str, Any]] = []
    cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=max_months * 30.5)

    try:
        url = (
            f"https://www.googleapis.com/youtube/v3/commentThreads"
            f"?part=snippet"
            f"&videoId={video_id}"
            f"&maxResults={min(max_comments, 100)}"
            f"&order=relevance"
            f"&key={key}"
        )

        req = urllib.request.Request(url, headers={"User-Agent": "MarketingCampaignAgent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))

        for item in data.get("items", []):
            if len(collected_comments) >= max_comments:
                break

            snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            author = snippet.get("authorDisplayName", "Unknown")
            text = snippet.get("textDisplay", snippet.get("textOriginal", "")).strip()
            published_str = snippet.get("publishedAt", "")
            likes = snippet.get("likeCount", 0)

            if not text:
                continue

            # Parse ISO date and check cutoff
            if published_str and max_months > 0:
                try:
                    # ISO 8601 parsing
                    pub_dt = datetime.datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                    if pub_dt < cutoff_date:
                        continue
                except Exception:
                    pass

            collected_comments.append({
                "author": author,
                "text": text,
                "published_at": published_str,
                "like_count": likes,
            })

    except Exception as e:
        logger.warning(f"[YouTube API] Could not fetch comments for video {video_id}: {e}")

    return collected_comments


def enrich_youtube_video_metadata(
    videos: list[dict[str, Any]], api_key: str
) -> list[dict[str, Any]]:
    """Add authoritative metadata to browser search results in API batches."""
    enriched = [dict(video) for video in videos]
    ids = list(dict.fromkeys(
        video_id for video_id in (extract_video_id(str(item.get("video_href", "")))
                                  for item in enriched) if video_id
    ))
    details: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]
        url = (
            "https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics"
            f"&id={','.join(batch)}&key={api_key}"
        )
        request = urllib.request.Request(url, headers={"User-Agent": "MarketingCampaignAgent/1.0"})
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        details.update({str(item.get("id")): item for item in payload.get("items", [])})

    for item in enriched:
        video_id = extract_video_id(str(item.get("video_href", "")))
        detail = details.get(video_id)
        item["video_id"] = video_id
        item["search_source"] = "playwright_fallback"
        if not detail:
            item["metadata_status"] = "unavailable"
            continue
        snippet = detail.get("snippet", {})
        statistics = detail.get("statistics", {})
        item.update({
            "video_title": snippet.get("title", item.get("video_title", "")).strip(),
            "video_description": snippet.get("description", "").strip()[:500],
            "channel_title": snippet.get("channelTitle", "").strip(),
            "default_language": snippet.get("defaultLanguage") or "unknown",
            "audio_language": snippet.get("defaultAudioLanguage") or "unknown",
            "published_at": snippet.get("publishedAt"),
            "view_count": int(statistics.get("viewCount", 0)),
            "comment_count": (int(statistics["commentCount"])
                              if statistics.get("commentCount") is not None else None),
            "metadata_status": "complete",
        })
        item["video_views"] = f"{format_view_count(item['view_count'])} views"
    return enriched


def search_and_collect_youtube_data(
    keywords: Union[list[str], str],
    min_views: int = 0,
    max_results_per_keyword: int = 50,
    api_key: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Master tool for YouTube video research and collection.
    Prioritizes official YouTube Data API v3 for high speed and reliability.
    Automatically falls back to Playwright scraper (youtube_search_tool) if API is unavailable.

    Args:
        keywords: List of keyword strings or a single keyword.
        min_views: Optional minimum view count. Defaults to zero.
        max_results_per_keyword: Up to 50 candidates per keyword.
        api_key: Optional API key.

    Returns:
        A list of dictionaries matching the required schema:
            [
                {
                    "video_keywords": str,
                    "video_title": str,
                    "video_href": str,
                    "video_views": str,
                    "video_description": str,
                    "channel_title": str,
                    "default_language": str,
                    "audio_language": str
                }
            ]
    """
    key = api_key or _get_api_key()

    api_error = None
    if key:
        try:
            logger.info("[YouTube Tool] Attempting search via official YouTube Data API v3...")
            results = search_youtube_videos_api(
                keywords=keywords,
                min_views=min_views,
                max_results_per_keyword=max_results_per_keyword,
                api_key=key,
            )
            if results:
                logger.info(f"[YouTube Tool] YouTube Data API v3 successfully returned {len(results)} videos.")
                return results
        except Exception as e:
            api_error = f"{type(e).__name__}: {e}"
            logger.warning(f"[YouTube Tool] YouTube Data API failed ({e}). Falling back to Playwright scraper...")

    # Fallback to Playwright scraper
    logger.info("[YouTube Tool] Executing Playwright fallback for YouTube search...")
    raw_results = search_youtube_videos(
        keywords=keywords,
        min_views=min_views,
        max_results_per_keyword=max_results_per_keyword,
    )

    # Ensure each item has 'video_keywords'
    if isinstance(keywords, str):
        kw_default = keywords.strip()
    elif isinstance(keywords, list) and keywords:
        kw_default = keywords[0]
    else:
        kw_default = "general"

    enriched_results: list[dict[str, Any]] = []
    for item in raw_results:
        entry = dict(item)
        if "video_keywords" not in entry:
            entry["video_keywords"] = kw_default
        entry["search_source"] = "playwright_fallback"
        entry["metadata_status"] = "missing"
        if api_error:
            entry["api_search_error"] = api_error
        enriched_results.append(entry)

    if key and enriched_results:
        try:
            return enrich_youtube_video_metadata(enriched_results, key)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.warning(f"[YouTube Tool] Could not enrich fallback metadata ({error}).")
            for entry in enriched_results:
                entry["metadata_status"] = "error"
                entry["metadata_error"] = error
    return enriched_results
