"""Playwright-based tool to search YouTube videos, apply popularity sorting, and filter by minimum views."""

import logging
import re
import urllib.parse
from typing import Any, Optional, Union

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

logger = logging.getLogger(__name__)


def parse_view_count(view_text: str) -> Optional[int]:
    """Parses a view count string (English and Spanish formats) into an integer.

    Examples:
        - "599K views" -> 599000
        - "1.2M views" -> 1200000
        - "500K visualizaciones" -> 500000
        - "1,5 M de visualizaciones" -> 1500000
        - "100.000 visualizaciones" -> 100000
        - "45K vistas" -> 45000
        - "123,456 views" -> 123456
    """
    if not view_text:
        return None

    cleaned = view_text.strip().lower()

    # Match numbers with M (millions)
    m_match = re.search(r"([\d.,]+)\s*(?:m|millones|m\b)", cleaned)
    if m_match:
        num_str = m_match.group(1).replace(",", ".")
        try:
            return int(float(num_str) * 1_000_000)
        except ValueError:
            pass

    # Match numbers with K / mil (thousands)
    k_match = re.search(r"([\d.,]+)\s*(?:k|mil\b)", cleaned)
    if k_match:
        num_str = k_match.group(1).replace(",", ".")
        try:
            return int(float(num_str) * 1_000)
        except ValueError:
            pass

    # Match numbers with B (billions)
    b_match = re.search(r"([\d.,]+)\s*(?:b|mil millones\b)", cleaned)
    if b_match:
        num_str = b_match.group(1).replace(",", ".")
        try:
            return int(float(num_str) * 1_000_000_000)
        except ValueError:
            pass

    # Match direct digit string with separators (e.g. 100.000 or 100,000)
    digit_match = re.search(r"([\d.,]+)", cleaned)
    if digit_match:
        num_str = digit_match.group(1)
        # If it has multiple dots or commas like 100.000 or 100,000
        if "." in num_str and "," in num_str:
            num_str = num_str.replace(".", "").replace(",", "")
        elif num_str.count(".") == 1 and len(num_str.split(".")[1]) == 3:
            num_str = num_str.replace(".", "")
        elif num_str.count(",") == 1 and len(num_str.split(",")[1]) == 3:
            num_str = num_str.replace(",", "")
        else:
            num_str = re.sub(r"[^\d]", "", num_str)

        try:
            return int(num_str)
        except ValueError:
            pass

    return None


def search_youtube_videos(
    keywords: Union[list[str], str],
    min_views: int = 100_000,
    max_results_per_keyword: int = 1,
) -> list[dict[str, Any]]:
    """Searches YouTube for videos matching given keywords, sorted by popularity,
    and returns videos that meet the minimum view threshold (>= 100K views).

    Args:
        keywords: A list of keyword strings or a single keyword string.
        min_views: Minimum number of views required (default: 100,000). Videos below this are skipped.
        max_results_per_keyword: Number of qualified videos to collect per keyword (default: 1).

    Returns:
        A list of dictionaries with structure:
            [
                {
                    "video_title": str,
                    "video_href": str,
                    "video_views": str
                }
            ]
    """
    if isinstance(keywords, str):
        kw_list = [keywords.strip()]
    elif isinstance(keywords, list):
        kw_list = [k.strip() for k in keywords if isinstance(k, str) and k.strip()]
    else:
        logger.warning(f"Invalid keywords argument provided: {keywords}")
        return []

    if not kw_list:
        return []

    collected_videos: list[dict[str, Any]] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="es-ES",
                extra_http_headers={
                    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                },
            )

            page = context.new_page()

            for kw in kw_list:
                try:
                    logger.info(f"Searching YouTube for keyword: '{kw}'")
                    encoded_kw = urllib.parse.quote_plus(kw)
                    # Use direct popularity sort parameter &sp=CAMSAhAB as base/reliable target
                    search_url = f"https://www.youtube.com/results?search_query={encoded_kw}&sp=CAMSAhAB"

                    try:
                        page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                    except PlaywrightTimeoutError:
                        logger.warning(f"Timeout loading search page for '{kw}', proceeding with available DOM.")

                    page.wait_for_timeout(2000)

                    # Handle Cookie Consent Popups if present
                    consent_selectors = [
                        "button:has-text('Aceptar todo')",
                        "button:has-text('Accept all')",
                        "button:has-text('Rechazar todo')",
                        "button[aria-label*='Aceptar' i]",
                        "button[aria-label*='Agree' i]",
                        "ytd-button-renderer:has-text('Aceptar')",
                    ]
                    for sel in consent_selectors:
                        try:
                            btn = page.query_selector(sel)
                            if btn and btn.is_visible():
                                btn.click()
                                page.wait_for_timeout(1000)
                                break
                        except Exception:
                            pass

                    # Wait for video renderers to appear
                    try:
                        page.wait_for_selector("ytd-video-renderer", timeout=10000)
                    except Exception:
                        logger.warning(f"No video renderers found for keyword: '{kw}'")
                        continue

                    # Extract video elements
                    video_elements = page.query_selector_all("ytd-video-renderer")
                    kw_collected_count = 0

                    for video_el in video_elements:
                        if kw_collected_count >= max_results_per_keyword:
                            break

                        # Extract Title and URL
                        title_anchor = video_el.query_selector("a#video-title")
                        if not title_anchor:
                            title_anchor = video_el.query_selector("a.yt-simple-endpoint.ytd-video-renderer")

                        if not title_anchor:
                            continue

                        title = (title_anchor.get_attribute("title") or title_anchor.inner_text() or "").strip()
                        href = title_anchor.get_attribute("href") or ""

                        if not title or not href:
                            continue

                        # Build absolute URL
                        if href.startswith("/"):
                            full_url = f"https://www.youtube.com{href}"
                        elif href.startswith("http"):
                            full_url = href
                        else:
                            full_url = f"https://www.youtube.com/{href}"

                        # Extract Views
                        views_text = ""
                        meta_items = video_el.query_selector_all("span.inline-metadata-item")
                        for item in meta_items:
                            text = item.inner_text().strip()
                            if any(w in text.lower() for w in ["view", "visualizaciones", "vistas", "k", "m"]):
                                views_text = text
                                break

                        # Fallback for views in aria-label or secondary metadata
                        if not views_text and meta_items:
                            views_text = meta_items[0].inner_text().strip()

                        # Parse and validate views against threshold
                        parsed_views = parse_view_count(views_text)

                        if parsed_views is not None and parsed_views < min_views:
                            logger.info(
                                f"Skipping video '{title}' - Views ({views_text} -> {parsed_views}) below threshold ({min_views})."
                            )
                            # Per instruction: If first video is less than 100K views, skip and bypass to next keyword
                            break

                        logger.info(
                            f"Found matching video: '{title}' ({views_text} -> {parsed_views or 'N/A'}) - {full_url}"
                        )
                        collected_videos.append({
                            "video_title": title,
                            "video_href": full_url,
                            "video_views": views_text or f"{parsed_views or min_views} views",
                        })
                        kw_collected_count += 1

                except Exception as e:
                    logger.error(f"Error processing keyword '{kw}': {e}", exc_info=True)
                    continue

            browser.close()

    except Exception as e:
        logger.error(f"Failed to run YouTube search scraper: {e}", exc_info=True)

    return collected_videos
