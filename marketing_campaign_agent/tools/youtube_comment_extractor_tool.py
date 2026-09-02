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


def _parse_videos_input(videos: Union[list[dict[str, Any]], list[str], str, Any]) -> list[str]:
    """Parses various input formats into a list of clean YouTube video URLs.

    Supported input formats:
      - List of dicts: [{"video_href": "https://..."}, {"URL": "https://..."}]
      - List of string URLs: ["https://www.youtube.com/watch?v=..."]
      - JSON string serializing a list of dicts or list of strings
      - Single URL string or comma/newline-separated URLs
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
                return _parse_videos_input(deserialized)
            except Exception:
                pass

        # If it's a plain string, check for multiple lines or commas
        lines = [line.strip() for line in re.split(r"[\n,]+", cleaned_str) if line.strip()]
        urls = []
        for line in lines:
            if "youtube.com" in line or "youtu.be" in line or len(line) == 11:
                urls.append(line)
        return urls

    if isinstance(videos, list):
        urls = []
        for item in videos:
            if isinstance(item, dict):
                # Search for url keys
                href = (
                    item.get("video_href")
                    or item.get("video_url")
                    or item.get("URL")
                    or item.get("url")
                    or item.get("link")
                    or item.get("href")
                    or ""
                )
                if href and isinstance(href, str) and href.strip():
                    urls.append(href.strip())
            elif isinstance(item, str) and item.strip():
                urls.append(item.strip())
        return urls

    if isinstance(videos, dict):
        href = (
            videos.get("video_href")
            or videos.get("video_url")
            or videos.get("URL")
            or videos.get("url")
            or ""
        )
        return [href.strip()] if href and isinstance(href, str) and href.strip() else []

    return []


def fetch_video_comments_api(
    video_id_or_url: str,
    max_comments: int = 50,
    max_months: int = 6,
    order: str = "time",
    api_key: Optional[str] = None,
) -> list[dict[str, str]]:
    """Fetches comments for a video using official YouTube Data API v3.

    Args:
        video_id_or_url: Video ID or YouTube watch URL.
        max_comments: Maximum comments to collect (default: 50).
        max_months: Filter comments published within max_months (default: 6).
        order: 'time' (newest first) or 'relevance' (top comments).
        api_key: Optional API key.

    Returns:
        List of comments with schema: [{"user": str, "comment": str, "when": str}]
    """
    key = api_key or _get_api_key()
    if not key:
        raise ValueError("No YouTube API key provided or found in environment variables.")

    video_id = extract_video_id(video_id_or_url)
    if not video_id:
        return []

    collected_comments: list[dict[str, str]] = []
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
            "part": "snippet",
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
            headers={"User-Agent": "MarketingCampaignAgent-CommentExtractor/1.0"},
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

            collected_comments.append({
                "user": author,
                "comment": text,
                "when": published_str,
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
    max_months: int = 6,
    order: str = "time",
) -> list[dict[str, str]]:
    """Fallback extractor using Playwright from youtube-comments-collector."""
    logger.info(f"[Playwright Fallback] Scraping comments for {video_url}")
    try:
        from youtube_scraper import YouTubeCommentScraper  # type: ignore

        sort_override = "newest" if order.lower() in ("time", "newest", "recent") else "top"
        scraper = YouTubeCommentScraper(
            headless=True,
            expand_replies=False,
            max_months=max_months,
        )

        scraped = scraper.scrape(
            url=video_url,
            max_comments=max_comments,
            sort_override=sort_override,
        )

        formatted: list[dict[str, str]] = []
        for item in scraped:
            formatted.append({
                "user": item.get("Author", "Unknown"),
                "comment": item.get("Msg", ""),
                "when": item.get("PublishedTime", f"< {max_months} months"),
            })
        return formatted

    except Exception as e:
        logger.error(f"[Playwright Fallback] Failed to scrape comments from {video_url}: {e}", exc_info=True)
        return []


def extract_comments_from_videos(
    videos: Union[list[dict[str, Any]], list[str], str, Any],
    max_comments_per_video: int = 50,
    max_months: int = 6,
    order: str = "time",
    api_key: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Iterates through YouTube videos, extracts comments filtered by date (<= 6 months),
    and returns a structured list of videos with their comments.

    Args:
        videos: Array of video objects containing 'video_href' (from YoutubeCommentsAnalyzer),
                list of URLs, or JSON string.
        max_comments_per_video: Max comments to extract per video (default: 50).
        max_months: Max comment age in months (default: 6).
        order: Sort order: 'time' (newest first) or 'relevance' (top comments).
        api_key: Optional YouTube API key.

    Returns:
        List of objects conforming to the schema:
        [
            {
                "video_href": "https://www.youtube.com/watch?v=...",
                "comments": [
                    {
                        "user": "@username",
                        "comment": "Comment text...",
                        "when": "2026-02-15T14:30:00Z"
                    }
                ]
            }
        ]
    """
    video_urls = _parse_videos_input(videos)
    if not video_urls:
        logger.warning(f"[Comment Extractor] No valid video URLs found in input: {videos}")
        return []

    key = api_key or _get_api_key()
    results: list[dict[str, Any]] = []

    for raw_url in video_urls:
        # Build canonical watch URL
        vid_id = extract_video_id(raw_url)
        full_url = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else raw_url

        logger.info(f"[Comment Extractor] Processing video {full_url} (max={max_comments_per_video}, months={max_months}, order={order})")
        video_comments: list[dict[str, str]] = []

        # 1. Try YouTube Data API v3 if key is available
        if key:
            try:
                video_comments = fetch_video_comments_api(
                    video_id_or_url=full_url,
                    max_comments=max_comments_per_video,
                    max_months=max_months,
                    order=order,
                    api_key=key,
                )
                logger.info(f"[Comment Extractor] API extracted {len(video_comments)} comments for {full_url}")
            except Exception as e:
                logger.warning(f"[Comment Extractor] YouTube Data API failed for {full_url}: {e}. Trying Playwright fallback...")
                video_comments = []

        # 2. Fallback to Playwright scraper if API failed or no key
        if not video_comments and not key:
            video_comments = fetch_video_comments_playwright(
                video_url=full_url,
                max_comments=max_comments_per_video,
                max_months=max_months,
                order=order,
            )
            logger.info(f"[Comment Extractor] Playwright extracted {len(video_comments)} comments for {full_url}")

        results.append({
            "video_href": full_url,
            "comments": video_comments,
        })

    return results
