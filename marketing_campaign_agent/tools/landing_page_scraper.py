"""Playwright-based tool to scrape and analyze landing pages for marketing copy research."""

from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright


def _attr_to_str(val: Any) -> str:
    """Helper to convert BeautifulSoup tag attribute values to a clean string."""
    if val is None:
        return ""
    if isinstance(val, (list, tuple)):
        return " ".join(str(item) for item in val)
    return str(val)


def scrape_landing_page(url: str) -> dict[str, Any]:
    """Scrapes a landing page using Playwright to extract marketing copy, headlines, CTAs,
    and detect video elements (VSL vs TSL).

    Args:
        url: The HTTP/HTTPS URL of the landing page to scrape.

    Returns:
        A dictionary containing:
            - url: Final loaded URL.
            - title: Page title.
            - meta_description: SEO/OpenGraph description if available.
            - suggested_page_type: 'VSL' if prominent video players are detected, otherwise 'TSL'.
            - video_detected: Boolean flag indicating if video elements or embeds are present.
            - video_sources: List of detected video URLs, iframes, or embed providers.
            - headings: List of major headings (h1, h2, h3) found on the page in order.
            - call_to_action_buttons: Text from buttons and CTA links.
            - main_content: Cleaned readable text and structure of the landing page.
    """
    cleaned_url = url.strip()
    if not cleaned_url.startswith(("http://", "https://")):
        cleaned_url = "https://" + cleaned_url

    parsed = urlparse(cleaned_url)
    if not parsed.netloc:
        return {"error": f"Invalid URL provided: '{url}'", "url": url}

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
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="es-ES",
                extra_http_headers={
                    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8,pt;q=0.7",
                },
            )

            page = context.new_page()

            # Navigate to page
            try:
                page.goto(cleaned_url, wait_until="domcontentloaded", timeout=30000)
            except PlaywrightTimeoutError:
                # Fallback if domcontentloaded timed out
                pass

            # Wait briefly for dynamic elements/hydration
            page.wait_for_timeout(2000)

            # Auto-scroll to trigger lazy-loaded sections, embeds, and CTAs
            try:
                page.evaluate(
                    """async () => {
                        await new Promise((resolve) => {
                            let totalHeight = 0;
                            const distance = 400;
                            const timer = setInterval(() => {
                                const scrollHeight = document.body.scrollHeight;
                                window.scrollBy(0, distance);
                                totalHeight += distance;
                                if (totalHeight >= scrollHeight || totalHeight >= 8000) {
                                    clearInterval(timer);
                                    window.scrollTo(0, 0);
                                    resolve();
                                }
                            }, 100);
                        });
                    }"""
                )
                page.wait_for_timeout(1000)
            except Exception:
                pass

            final_url = page.url
            html_content = page.content()
            page_title = page.title()

            browser.close()

        # Parse HTML using BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")

        # Extract Meta Description
        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"}) or soup.find(
            "meta", attrs={"property": "og:description"}
        )
        if meta_tag:
            meta_desc = _attr_to_str(meta_tag.get("content")).strip()

        # Video Detection (VSL vs TSL)
        video_sources: list[str] = []
        video_keywords = [
            "youtube",
            "vimeo",
            "wistia",
            "loom",
            "vidalytics",
            "vturb",
            "pandavideo",
            "converteai",
            "bunny",
            "smartplayer",
            "evplayer",
            "video",
        ]

        # Check <video> and <source> tags
        for video_tag in soup.find_all(["video", "source"]):
            src_str = _attr_to_str(video_tag.get("src")).strip()
            if src_str:
                video_sources.append(src_str)

        # Check <iframe> embeds
        for iframe in soup.find_all("iframe"):
            src_str = _attr_to_str(iframe.get("src") or iframe.get("data-src")).strip()
            if src_str and any(kw in src_str.lower() for kw in video_keywords):
                video_sources.append(src_str)

        # Check video player container elements
        for element in soup.find_all(["div", "section"]):
            elem_id = _attr_to_str(element.get("id")).lower()
            elem_class = _attr_to_str(element.get("class")).lower()
            if any(kw in elem_id for kw in ["player", "video", "vsl", "vturb"]) or any(
                kw in elem_class for kw in ["player", "video-wrapper", "vsl-container", "vturb"]
            ):
                video_sources.append(f"player_container: id='{elem_id}', class='{elem_class}'")

        video_sources = list(dict.fromkeys(video_sources))  # Deduplicate
        video_detected = len(video_sources) > 0
        suggested_page_type = "VSL" if video_detected else "TSL"

        # Extract Headings (h1, h2, h3)
        headings: list[dict[str, str]] = []
        for h in soup.find_all(["h1", "h2", "h3"]):
            text = h.get_text(strip=True)
            if text and len(text) > 2:
                headings.append({"level": h.name, "text": text})

        # Extract CTA Buttons & Action Links
        cta_buttons: list[str] = []
        cta_selectors = [
            "button",
            "input[type='submit']",
            "input[type='button']",
            "a[href*='checkout']",
            "a[href*='hotmart']",
            "a[href*='pay']",
            "a[href*='kiwify']",
            "a[href*='clickbank']",
            "a[href*='buy']",
            "a[class*='btn']",
            "a[class*='button']",
            "a[class*='cta']",
        ]
        for cta in soup.select(", ".join(cta_selectors)):
            text = cta.get_text(strip=True) or _attr_to_str(cta.get("value")).strip()
            if text and 2 < len(text) < 100:
                cta_buttons.append(text)

        cta_buttons = list(dict.fromkeys(cta_buttons))[:15]  # Deduplicate and limit

        # Remove irrelevant noise tags for clean copy extraction
        for tag in soup(["script", "style", "noscript", "svg", "canvas", "nav", "meta", "link"]):
            tag.decompose()

        # Extract structured text paragraphs and bullet points
        text_lines: list[str] = []
        for elem in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
            text = elem.get_text(separator=" ", strip=True)
            if text and len(text) > 3:
                # Format bullet points and headings
                if elem.name in ["h1", "h2", "h3", "h4"]:
                    text_lines.append(f"\n### {text}")
                elif elem.name == "li":
                    text_lines.append(f"- {text}")
                else:
                    text_lines.append(text)

        raw_text = "\n".join(text_lines)
        # Limit main content to 25,000 characters to stay within context budgets
        trimmed_content = raw_text[:25000] + ("\n...[Content truncated]" if len(raw_text) > 25000 else "")

        return {
            "url": final_url,
            "title": page_title,
            "meta_description": meta_desc,
            "suggested_page_type": suggested_page_type,
            "video_detected": video_detected,
            "video_sources": video_sources[:5],
            "headings": headings[:20],
            "call_to_action_buttons": cta_buttons,
            "main_content": trimmed_content,
        }

    except Exception as exc:
        return {
            "error": f"Failed to scrape landing page at {url}: {exc}",
            "url": url,
        }
