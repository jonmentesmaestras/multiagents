"""Tool for extracting YouTube comments from video URLs using YouTube Data API v3 with Playwright fallback."""

import datetime
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional, Union
import urllib.error
import urllib.parse
import urllib.request
from dotenv import find_dotenv, load_dotenv

from .youtube_api_tool import _get_api_key, extract_video_id

logger = logging.getLogger(__name__)

# Ensure youtube-comments-collector is accessible in sys.path for fallback
_COLLECTOR_DIR = Path(__file__).resolve().parent.parent.parent / "youtube-comments-collector"
if _COLLECTOR_DIR.exists() and str(_COLLECTOR_DIR) not in sys.path:
    sys.path.insert(0, str(_COLLECTOR_DIR))


def _normalize_youtube_url(url_or_id: str) -> str:
    """Normalizes any YouTube URL or ID into a canonical watch URL: https://www.youtube.com/watch?v={video_id}"""
    if not url_or_id:
        return ""
    clean = url_or_id.strip()
    vid_id = extract_video_id(clean)
    if vid_id:
        return f"https://www.youtube.com/watch?v={vid_id}"
    return clean


def _parse_video_entries(videos: Union[list[dict[str, Any]], list[str], str, Any]) -> list[dict[str, str]]:
    """Parses various input formats into a list of normalized video dictionaries with URLs and keywords.

    Supported input formats:
      - List of dicts: [{"video_href": "https://...", "video_keywords": "velas artesanales"}, ...]
      - List of string URLs: ["https://www.youtube.com/watch?v=..."]
      - JSON string serializing a list of dicts or list of strings
      - Single URL string or comma/newline-separated URLs

    Returns:
      List of dicts: [{"video_href": str, "video_keywords": str, "video_title": str}]
    """
    if not videos:
        return []

    # If it's a JSON string, deserialize first
    if isinstance(videos, str):
        cleaned_str = videos.strip()
        if (cleaned_str.startswith("[") and cleaned_str.endswith("]")) or (
            cleaned_str.startswith("{") and cleaned_str.endswith("}")
        ):
            try:
                deserialized = json.loads(cleaned_str)
                return _parse_video_entries(deserialized)
            except Exception:
                pass

        # If it's a plain string, check for multiple lines or commas
        lines = [line.strip() for line in re.split(r"[\n,]+", cleaned_str) if line.strip()]
        entries = []
        for line in lines:
            if "youtube.com" in line or "youtu.be" in line or len(line) == 11 or line.startswith("http"):
                entries.append({
                    "video_href": _normalize_youtube_url(line),
                    "video_keywords": "",
                    "video_title": "",
                })
        return entries

    if isinstance(videos, list):
        entries = []
        for item in videos:
            if isinstance(item, dict):
                href = (
                    item.get("video_href")
                    or item.get("video_url")
                    or item.get("URL")
                    or item.get("url")
                    or item.get("link")
                    or item.get("href")
                    or ""
                )
                keywords = (
                    item.get("video_keywords")
                    or item.get("keywords")
                    or item.get("keyword")
                    or ""
                )
                title = (
                    item.get("video_title")
                    or item.get("title")
                    or item.get("Title")
                    or ""
                )
                if href and isinstance(href, str) and href.strip():
                    entries.append({
                        "video_href": _normalize_youtube_url(href),
                        "video_keywords": str(keywords).strip(),
                        "video_title": str(title).strip(),
                    })
            elif isinstance(item, str) and item.strip():
                entries.append({
                    "video_href": _normalize_youtube_url(item),
                    "video_keywords": "",
                    "video_title": "",
                })
        return entries

    if isinstance(videos, dict):
        href = (
            videos.get("video_href")
            or videos.get("video_url")
            or videos.get("URL")
            or videos.get("url")
            or ""
        )
        keywords = videos.get("video_keywords") or videos.get("keywords") or ""
        title = videos.get("video_title") or videos.get("title") or ""
        if href and isinstance(href, str) and href.strip():
            return [{
                "video_href": _normalize_youtube_url(href),
                "video_keywords": str(keywords).strip(),
                "video_title": str(title).strip(),
            }]

    return []


def _parse_videos_input(videos: Union[list[dict[str, Any]], list[str], str, Any]) -> list[str]:
    """Parses various input formats into a list of clean YouTube video URLs for backward compatibility."""
    entries = _parse_video_entries(videos)
    return [e["video_href"] for e in entries]


def get_video_comment_count_api(
    video_id_or_url: str,
    api_key: Optional[str] = None,
) -> int:
    """Fetches the total comment count for a video using YouTube Data API v3 statistics."""
    key = api_key or _get_api_key()
    if not key:
        return 0

    video_id = extract_video_id(video_id_or_url)
    if not video_id:
        return 0

    query_params = urllib.parse.urlencode({
        "part": "statistics",
        "id": video_id,
        "key": key,
    })
    url = f"https://www.googleapis.com/youtube/v3/videos?{query_params}"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "MarketingCampaignAgent-CommentCollector/1.0"},
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
        items = data.get("items", [])
        if not items:
            return 0
        stats = items[0].get("statistics", {})
        count_str = stats.get("commentCount", "0")
        return int(count_str)
    except Exception as e:
        logger.warning(f"Failed to fetch commentCount for video {video_id}: {e}")
        return 0


def fetch_video_comments_api(
    video_id_or_url: str,
    max_comments: int = 50,
    max_months: int = 3,
    min_comments_threshold: int = 100,
    order: str = "time",
    api_key: Optional[str] = None,
) -> Optional[list[dict[str, Any]]]:
    """Fetches comments for a video using official YouTube Data API v3.
    Bypasses the video if total comments <= min_comments_threshold.

    Args:
        video_id_or_url: Video ID or YouTube watch URL.
        max_comments: Maximum comments to collect (default: 50).
        max_months: Filter comments published within max_months (default: 3).
        min_comments_threshold: Minimum total comments required to process video (default: 100).
        order: 'time' (newest first) or 'relevance' (top comments).
        api_key: Optional API key.

    Returns:
        List of comments with schema: [{"Author": str, "Msg": str, "Reply": list}]
        or None if video is bypassed because total comments <= min_comments_threshold.
    """
    key = api_key or _get_api_key()
    if not key:
        raise ValueError("No YouTube API key provided or found in environment variables.")

    video_id = extract_video_id(video_id_or_url)
    if not video_id:
        return []

    # 1. Check total comments threshold (> 100)
    if min_comments_threshold > 0:
        total_count = get_video_comment_count_api(video_id, api_key=key)
        if total_count <= min_comments_threshold:
            logger.info(
                f"[Comment Collector] Video {video_id} has {total_count} comments (<= {min_comments_threshold}). Bypassing."
            )
            return None

    collected_comments: list[dict[str, Any]] = []
    cutoff_date = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=max_months * 30.5)
        if max_months > 0
        else None
    )

    api_order = "time" if order.lower() in ("time", "newest", "recent") else "relevance"
    page_token = ""

    while len(collected_comments) < max_comments:
        per_page = min(max_comments - len(collected_comments), 100)
        query_params = {
            "part": "snippet,replies",
            "videoId": video_id,
            "maxResults": str(per_page),
            "order": api_order,
            "key": key,
        }
        if page_token:
            query_params["pageToken"] = page_token

        encoded_params = urllib.parse.urlencode(query_params)
        url = f"https://www.googleapis.com/youtube/v3/commentThreads?{encoded_params}"

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "MarketingCampaignAgent-CommentCollector/1.0"},
        )

        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))

        items = data.get("items", [])
        if not items:
            break

        stop_pagination = False
        for item in items:
            if len(collected_comments) >= max_comments:
                break

            top_snippet = (
                item.get("snippet", {})
                .get("topLevelComment", {})
                .get("snippet", {})
            )
            author = top_snippet.get("authorDisplayName", "Unknown")
            text = top_snippet.get("textDisplay", top_snippet.get("textOriginal", "")).strip()
            published_str = top_snippet.get("publishedAt", "")

            if not text:
                continue

            # Check cutoff date
            if published_str and cutoff_date:
                try:
                    pub_dt = datetime.datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                    if pub_dt < cutoff_date:
                        # If ordered by time (newest first), older comments mean subsequent comments are even older
                        if api_order == "time":
                            stop_pagination = True
                            break
                        continue
                except Exception:
                    pass

            # Extract replies if available
            raw_replies = item.get("replies", {}).get("comments", [])
            reply_list: list[dict[str, Any]] = []
            for r in raw_replies:
                r_snippet = r.get("snippet", {})
                r_author = r_snippet.get("authorDisplayName", "Unknown")
                r_text = r_snippet.get("textDisplay", r_snippet.get("textOriginal", "")).strip()
                if r_text:
                    reply_list.append({
                        "Author": r_author,
                        "Msg": r_text,
                    })

            collected_comments.append({
                "Author": author,
                "Msg": text,
                "Reply": reply_list,
            })

        if stop_pagination:
            break

        page_token = data.get("nextPageToken", "")
        if not page_token:
            break

    return collected_comments


def fetch_video_comments_playwright(
    video_url: str,
    max_comments: int = 50,
    max_months: int = 3,
    min_comments_threshold: int = 100,
    order: str = "time",
) -> Optional[list[dict[str, Any]]]:
    """Fallback extractor using Playwright from youtube-comments-collector."""
    logger.info(f"[Playwright Fallback] Scraping comments for {video_url} (min_threshold={min_comments_threshold})")
    try:
        from youtube_scraper import YouTubeCommentScraper  # type: ignore

        sort_override = "newest" if order.lower() in ("time", "newest", "recent") else "top"
        scraper = YouTubeCommentScraper(
            headless=True,
            expand_replies=True,
            max_months=max_months,
            min_comments_threshold=min_comments_threshold,
        )

        scraped = scraper.scrape(
            url=video_url,
            max_comments=max_comments,
            sort_override=sort_override,
        )

        if not scraped and min_comments_threshold > 0:
            # Check if bypassed or empty
            return None

        formatted: list[dict[str, Any]] = []
        for item in scraped:
            formatted.append({
                "Author": item.get("Author", "Unknown"),
                "Msg": item.get("Msg", ""),
                "Reply": item.get("Reply", []),
            })
        return formatted

    except Exception as e:
        logger.error(f"[Playwright Fallback] Failed to scrape comments from {video_url}: {e}", exc_info=True)
        return []


def extract_comments_from_videos(
    videos: Union[list[dict[str, Any]], list[str], str, Any],
    max_comments_per_video: int = 50,
    max_months: int = 3,
    min_comments_threshold: int = 100,
    order: str = "time",
    api_key: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Iterates through YouTube videos, checks total comments > 100, extracts comments
    from 3 months ago to the most current comment sorted by newest, and returns a structured JSON.

    If total comments <= 100, the video is bypassed and skipped.

    Args:
        videos: Array of video objects containing 'video_href' and 'video_keywords'
                (e.g., output of YoutubeCommentsAnalyzer), list of URLs, or JSON string.
        max_comments_per_video: Max comments to extract per video (default: 50).
        max_months: Max comment age in months (default: 3).
        min_comments_threshold: Minimum comments required to process video (default: 100).
        order: Sort order: 'time' (newest first) or 'relevance'.
        api_key: Optional YouTube API key.

    Returns:
        List of objects conforming to the schema:
        [
            {
                "video_href": "https://www.youtube.com/watch?v=...",
                "video_keywords": "como hacer velas artesanales para vender",
                "3_months_comments": [
                    {
                        "Author": "@user_handle",
                        "Msg": "Comment message...",
                        "Reply": []
                    }
                ]
            }
        ]
    """
    video_entries = _parse_video_entries(videos)
    if not video_entries:
        logger.warning(f"[Comment Collector] No valid video entries found in input: {videos}")
        return []

    key = api_key or _get_api_key()
    results: list[dict[str, Any]] = []

    for entry in video_entries:
        full_url = entry["video_href"]
        keywords = entry.get("video_keywords", "")

        logger.info(
            f"[Comment Collector] Processing {full_url} (keywords='{keywords}', threshold={min_comments_threshold}, months={max_months})"
        )
        video_comments: Optional[list[dict[str, Any]]] = None

        # 1. Try YouTube Data API v3 if key is available
        if key:
            try:
                video_comments = fetch_video_comments_api(
                    video_id_or_url=full_url,
                    max_comments=max_comments_per_video,
                    max_months=max_months,
                    min_comments_threshold=min_comments_threshold,
                    order=order,
                    api_key=key,
                )
            except Exception as e:
                logger.warning(
                    f"[Comment Collector] YouTube Data API failed for {full_url}: {e}. Trying Playwright fallback..."
                )
                video_comments = None

        # 2. Fallback to Playwright scraper if API failed or no key
        if video_comments is None and not key:
            video_comments = fetch_video_comments_playwright(
                video_url=full_url,
                max_comments=max_comments_per_video,
                max_months=max_months,
                min_comments_threshold=min_comments_threshold,
                order=order,
            )

        # 3. Check if bypassed due to total comments <= 100
        if video_comments is None:
            logger.info(f"[Comment Collector] Bypassing URL {full_url} (total comments <= {min_comments_threshold} or unavailable).")
            continue

        results.append({
            "video_href": full_url,
            "video_keywords": keywords,
            "3_months_comments": video_comments,
        })

    return results


# Aliases
collect_youtube_comments = extract_comments_from_videos
