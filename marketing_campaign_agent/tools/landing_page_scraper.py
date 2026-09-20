"""Asynchronous landing extraction with explicit failures and auditable page copy."""

import asyncio
import sys
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
import httpx
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
}


def _attr_to_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, (list, tuple)):
        return " ".join(str(item) for item in val)
    return str(val)


def content_error(title: str, content: str) -> str | None:
    """Reject empty extracts and common HTTP-200 challenge/error documents."""
    if not isinstance(content, str):
        return "La página no contiene suficiente texto para analizar su oferta."
    error_titles = ("access denied", "just a moment", "page not found", "403 forbidden",
                    "404 not found", "verify you are human", "attention required",
                    "javascript required")
    challenge_text = ("verify you are human", "checking your browser",
                      "enable javascript and cookies to continue",
                      "this site requires javascript", "javascript is disabled",
                      "enable javascript in your browser", "please enable javascript",
                      "you need to enable javascript to run this app")
    if any(x in title.lower() for x in error_titles) or any(
        x in content[:1500].lower() for x in challenge_text
    ):
        return "La página devolvió un bloqueo de acceso o una página de error."
    if len(content.split()) <= 20:
        return "La página no contiene suficiente texto para analizar su oferta."
    return None


async def scrape_landing_page(url: str) -> dict[str, Any]:
    """Extract the specific landing's headings, CTAs, video hints and main_content.

    Returns an explicit error (without main_content) on navigation or extraction
    failure. requested_url and url distinguish the input from the final redirect.
    """
    cleaned_url = url.strip()
    if "://" not in cleaned_url:
        cleaned_url = "https://" + cleaned_url
    parsed = urlparse(cleaned_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"error": "URL HTTP/HTTPS inválida.", "url": url}
    try:
        # Uvicorn on Windows may use SelectorEventLoop, which cannot start the
        # Playwright subprocess. All browser objects then live in their own loop.
        if sys.platform == "win32" and isinstance(
            asyncio.get_running_loop(), asyncio.SelectorEventLoop
        ):
            result = await asyncio.to_thread(_scrape_on_windows_loop, cleaned_url)
        else:
            result = await _scrape_page(cleaned_url)
        result["requested_url"] = cleaned_url
        return result
    except Exception as exc:
        return {
            "error": f"No se pudo extraer la landing: {type(exc).__name__}: {exc}",
            "url": cleaned_url,
            "requested_url": cleaned_url,
            "extraction_method": "browser",
        }


def _scrape_on_windows_loop(url: str) -> dict[str, Any]:
    with asyncio.Runner(loop_factory=asyncio.ProactorEventLoop) as runner:
        return runner.run(_scrape_page(url))


async def _scrape_page(url: str) -> dict[str, Any]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await context.new_page()
            documents = []
            def remember_document(reply):
                if reply.request.is_navigation_request() and reply.frame == page.main_frame:
                    documents.append(reply)
            page.on("response", remember_document)
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if (response is not None and response.status == 403
                    and response.headers.get("cf-mitigated") == "challenge"):
                try:
                    await page.wait_for_function(r"""() => {
                        const title = document.title.toLowerCase();
                        return document.body && document.body.innerText.length > 100
                            && !/just a moment|un momento|attention required/.test(title)
                            && !/security verification|verificación de seguridad|verify you are human/i
                                .test(document.body.innerText);
                    }""", timeout=10000)
                except PlaywrightTimeoutError:
                    pass
                if documents:
                    response = documents[-1]
            # Some page builders reject automated Chromium while serving the
            # same public HTML to a regular HTTP client. Keep the fallback
            # limited to that access-denied response and validate its content
            # through the same extraction path below.
            if response is not None and response.status == 403:
                return await _scrape_page_http(url)
            if response is None or response.status >= 400:
                status = response.status if response else "sin respuesta"
                return {"error": f"La navegación falló: HTTP {status}.", "url": page.url}
            if urlparse(page.url).scheme not in ("http", "https"):
                return {"error": "La navegación terminó en una URL inválida.", "url": page.url}
            await page.locator("body").wait_for(state="visible", timeout=10000)
            await page.wait_for_timeout(2000)
            await page.evaluate("""async () => {
                const limit = Math.min(document.body.scrollHeight, 8000);
                for (let y = 0; y < limit; y += 400) {
                    window.scrollTo(0, y);
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                window.scrollTo(0, 0);
            }""")
            await page.wait_for_timeout(1000)
            result = extract_landing_content(await page.content(), page.url, await page.title())
            # A client-rendered landing may still be showing its initial shell.
            # Give it one bounded opportunity to replace that shell with real
            # offer copy. If it does not, preserve the explicit extraction
            # failure so the orchestrator can request a PDF/screenshots.
            if result.get("error"):
                try:
                    await page.wait_for_function(r"""() => {
                        const text = document.body?.innerText || '';
                        return text.trim().split(/\s+/).length > 20
                            && !/this site requires javascript|javascript is disabled|enable javascript in your browser|please enable javascript|you need to enable javascript to run this app/i.test(text);
                    }""", timeout=5000)
                    await page.wait_for_timeout(500)
                    result = extract_landing_content(
                        await page.content(), page.url, await page.title())
                except PlaywrightTimeoutError:
                    pass
            result["http_status"] = response.status
            result.setdefault("extraction_method", "browser")
            return result
        finally:
            await browser.close()


async def _scrape_page_http(url: str) -> dict[str, Any]:
    """Recover public landing HTML when an automated browser receives 403."""
    async with httpx.AsyncClient(
        headers=_HTTP_HEADERS, follow_redirects=True, timeout=30.0
    ) as client:
        response = await client.get(url)
    if response.status_code >= 400:
        return {
            "error": f"La navegación falló: HTTP 403 y respaldo HTTP {response.status_code}.",
            "url": str(response.url),
        }
    final_url = str(response.url)
    if urlparse(final_url).scheme not in ("http", "https"):
        return {"error": "La navegación terminó en una URL inválida.", "url": final_url}
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    result = extract_landing_content(response.text, final_url, title)
    result["http_status"] = response.status_code
    result["extraction_method"] = "http_fallback"
    return result


def extract_landing_content(html_content: str, final_url: str, page_title: str) -> dict[str, Any]:
    """Extract central page copy; metadata is context, not claim evidence."""
    # Parse HTML using BeautifulSoup
    soup = BeautifulSoup(html_content, "html.parser")

    # Extract Meta Description
    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    if meta_tag:
        meta_desc = _attr_to_str(meta_tag.get("content")).strip()

    page_language = _attr_to_str(soup.html.get("lang")) if soup.html else ""
    # Discard site navigation before extracting headings, CTAs, or evidence.
    for tag in soup.select("nav, footer, body > header, [role='banner'], [role='navigation'], [role='contentinfo'], [hidden], [aria-hidden='true']"):
        tag.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    main = soup.select_one("main, [role='main'], #SITE_PAGES")
    if main is not None:
        soup = main
    elif soup.body is not None:
        soup = soup.body

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
        text = h.get_text(separator=" ", strip=True)
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

    # Read text nodes so div/span-based builders are not silently omitted.
    # Explicit author sections are kept for auditing, outside claim evidence.
    text_lines: list[str] = []
    secondary_lines: list[str] = []
    biography_level = None
    biography_headings = {
        "meet your instructor", "about the author", "about the instructor",
        "sobre el autor", "sobre la autora", "conoce a tu instructor",
        "sobre o autor", "sobre a autora", "conheça seu instrutor",
    }
    for node in soup.descendants:
        if isinstance(node, Tag) and node.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(node.name[1])
            if biography_level is not None and level <= biography_level:
                biography_level = None
            if node.get_text(" ", strip=True).casefold().rstrip(":") in biography_headings:
                biography_level = level
        elif isinstance(node, NavigableString) and node.strip():
            (secondary_lines if biography_level is not None else text_lines).append(node.strip())

    raw_text = "\n".join(text_lines)
    problem = content_error(page_title, raw_text)
    if problem:
        return {"error": problem, "url": final_url}
    # Limit main content to 25,000 characters to stay within context budgets
    trimmed_content = raw_text[:25000] + ("\n...[Content truncated]" if len(raw_text) > 25000 else "")

    return {
        "url": final_url,
        "title": page_title,
        "page_language": page_language or None,
        "content_truncated": len(raw_text) > 25000,
        "meta_description": meta_desc,
        "suggested_page_type": suggested_page_type,
        "video_detected": video_detected,
        "video_sources": video_sources[:5],
        "headings": headings[:20],
        "call_to_action_buttons": cta_buttons,
        "main_content": trimmed_content,
        "secondary_content": "\n".join(secondary_lines)[:5000],
    }
