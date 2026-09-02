"""Core Playwright scraper engine for YouTube comments with date filtering."""

from __future__ import annotations
import asyncio
import logging
from typing import List, Dict, Any, Optional, Set
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from .models import YouTubeComment, validate_comments_data
from .parser import parse_comment_count, is_within_time_limit, parse_relative_time_months
from .selectors import (
    VIDEO_TITLE_SELECTORS,
    COUNT_HEADER_SELECTORS,
    SORT_DROPDOWN_BUTTON_SELECTORS,
    SORT_OPTION_NEWEST_SELECTORS,
    COMMENTS_CONTAINER_SELECTORS,
    COMMENT_THREAD_SELECTORS,
    COMMENT_MSG_SELECTORS,
    COMMENT_AUTHOR_SELECTORS,
    PUBLISHED_TIME_SELECTORS,
    CONSENT_BUTTON_SELECTORS,
    REPLIES_MORE_BUTTON_SELECTORS,
    REPLIES_CONTAINER_SELECTORS,
)

logger = logging.getLogger("youtube_scraper")


class YouTubeCommentScraper:
    """
    Playwright-based scraper for YouTube video comments with time filtering.
    """

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 30000,
        scroll_pause_ms: int = 1200,
        max_scroll_attempts: int = 60,
        expand_replies: bool = False,
        sort_threshold: int = 500,
        max_months: Optional[int] = 6,
        min_comments_threshold: Optional[int] = None,
        browser_type: str = "chromium",
    ):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.scroll_pause_ms = scroll_pause_ms
        self.max_scroll_attempts = max_scroll_attempts
        self.expand_replies = expand_replies
        self.sort_threshold = sort_threshold
        self.max_months = max_months
        self.min_comments_threshold = min_comments_threshold
        self.browser_type = browser_type

    async def _handle_consent(self, page: Page) -> None:
        """Dismiss YouTube cookie / consent dialogs if present."""
        for selector in CONSENT_BUTTON_SELECTORS:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=1500):
                    logger.info(f"Clicking consent dialog button: {selector}")
                    await btn.click()
                    await page.wait_for_timeout(1000)
                    break
            except Exception:
                continue

    async def _get_video_title(self, page: Page) -> str:
        """Extract the video title from page."""
        for selector in VIDEO_TITLE_SELECTORS:
            try:
                el = page.locator(selector).first
                if await el.is_visible(timeout=1000):
                    title_text = await el.inner_text()
                    title_clean = title_text.strip()
                    if title_clean:
                        return title_clean
            except Exception:
                continue

        # Fallback to page title
        try:
            page_title = await page.title()
            if page_title:
                return page_title.replace(" - YouTube", "").strip()
        except Exception:
            pass

        return "Unknown Video Title"

    async def _extract_comment_count(self, page: Page) -> int:
        """
        Locate the comments header and parse the total comments count.
        Specifically searches for count text inside:
        <h2 id="count" class="style-scope ytd-comments-header-renderer">
          <yt-formatted-string class="count-text style-scope ytd-comments-header-renderer">
            <span dir="auto" class="style-scope yt-formatted-string">...</span>
        """
        for scroll_y in [400, 700, 1000]:
            await page.evaluate(f"window.scrollTo(0, {scroll_y});")
            await page.wait_for_timeout(800)

            for selector in COUNT_HEADER_SELECTORS:
                try:
                    count_el = page.locator(selector).first
                    if await count_el.is_visible(timeout=1500):
                        raw_text = await count_el.inner_text()
                        if raw_text and any(c.isdigit() for c in raw_text):
                            parsed = parse_comment_count(raw_text)
                            logger.info(f"Found comment count element with text '{raw_text}' -> parsed: {parsed}")
                            return parsed
                except Exception:
                    continue

        logger.warning("Could not find or parse comments count header element.")
        return 0

    async def _sort_by_newest(self, page: Page) -> bool:
        """
        Click 'Sort by' dropdown and select 'Newest first'.
        <div id="icon-label" class="style-scope yt-dropdown-menu">Sort by</div>
        and click <div class="item style-scope yt-dropdown-menu">...</div>
        """
        logger.info("Triggering sort by Newest first...")

        # 1. Click Sort By button
        sort_clicked = False
        for selector in SORT_DROPDOWN_BUTTON_SELECTORS:
            try:
                sort_btn = page.locator(selector).first
                if await sort_btn.is_visible(timeout=2000):
                    await sort_btn.scroll_into_view_if_needed()
                    await sort_btn.click()
                    sort_clicked = True
                    logger.info(f"Clicked Sort By button: {selector}")
                    await page.wait_for_timeout(800)
                    break
            except Exception as e:
                logger.debug(f"Could not click sort button with {selector}: {e}")
                continue

        if not sort_clicked:
            try:
                clicked_via_js = await page.evaluate('''() => {
                    const btn = document.querySelector('div#icon-label.style-scope.yt-dropdown-menu') ||
                                document.querySelector('yt-sort-filter-sub-menu-renderer #icon-label') ||
                                document.querySelector('ytd-comments-header-renderer #sort-menu');
                    if (btn) {
                        btn.click();
                        return true;
                    }
                    return false;
                }''')
                if clicked_via_js:
                    sort_clicked = True
                    await page.wait_for_timeout(800)
            except Exception:
                pass

        if not sort_clicked:
            logger.warning("Could not locate or click the 'Sort by' button.")
            return False

        # 2. Click 'Newest first' option in dropdown
        option_clicked = False
        for selector in SORT_OPTION_NEWEST_SELECTORS:
            try:
                option = page.locator(selector).first
                if await option.is_visible(timeout=2000):
                    await option.click()
                    option_clicked = True
                    logger.info(f"Clicked 'Newest first' option: {selector}")
                    await page.wait_for_timeout(1500)
                    break
            except Exception as e:
                logger.debug(f"Could not click newest option with {selector}: {e}")
                continue

        if not option_clicked:
            try:
                clicked_opt_js = await page.evaluate('''() => {
                    const items = document.querySelectorAll('tp-yt-paper-listbox.style-scope.yt-dropdown-menu a, ytd-menu-service-item-renderer, div.item.style-scope.yt-dropdown-menu');
                    if (items && items.length >= 2) {
                        items[1].click();
                        return true;
                    }
                    return false;
                }''')
                if clicked_opt_js:
                    option_clicked = True
                    await page.wait_for_timeout(1500)
            except Exception:
                pass

        if not option_clicked:
            logger.warning("Could not select 'Newest first' from dropdown.")
            return False

        return True

    async def _extract_published_time(self, el) -> Optional[str]:
        """
        Extract published relative time string from comment element.
        Target: <span dir="auto" id="published-time-text" class="style-scope ytd-comment-view-model">
                  <a class="yt-simple-endpoint style-scope ytd-comment-view-model" href="...">6 months ago</a>
                </span>
        """
        for selector in PUBLISHED_TIME_SELECTORS:
            try:
                time_el = el.locator(selector).first
                if await time_el.is_visible(timeout=200):
                    txt = (await time_el.inner_text()).strip()
                    if txt:
                        return txt
            except Exception:
                continue
        return None

    async def _extract_replies_for_thread(self, thread_locator) -> List[Dict[str, Any]]:
        """Optionally expand and extract comment replies for a thread."""
        replies_data: List[Dict[str, Any]] = []
        if not self.expand_replies:
            return replies_data

        try:
            for more_sel in REPLIES_MORE_BUTTON_SELECTORS:
                more_btn = thread_locator.locator(more_sel).first
                if await more_btn.is_visible(timeout=500):
                    await more_btn.click()
                    await asyncio.sleep(0.6)
                    break

            for reply_sel in REPLIES_CONTAINER_SELECTORS:
                reply_els = await thread_locator.locator(reply_sel).all()
                if reply_els:
                    for r_el in reply_els:
                        author = ""
                        msg = ""
                        # Extract author
                        for a_sel in COMMENT_AUTHOR_SELECTORS:
                            a_loc = r_el.locator(a_sel).first
                            if await a_loc.is_visible(timeout=250):
                                author = (await a_loc.inner_text()).strip()
                                break

                        if not author:
                            try:
                                href_el = r_el.locator('a[href*="/@"], a#author-text').first
                                if await href_el.count() > 0:
                                    href_val = await href_el.get_attribute("href")
                                    if href_val and "/@" in href_val:
                                        author = "@" + href_val.split("/@")[-1].split("/")[0].split("?")[0]
                            except Exception:
                                pass

                        # Extract message
                        for m_sel in COMMENT_MSG_SELECTORS:
                            m_loc = r_el.locator(m_sel).first
                            if await m_loc.is_visible(timeout=250):
                                text_val = (await m_loc.inner_text()).strip()
                                if text_val and not text_val.startswith("Pinned by") and not text_val.startswith("Fijado por"):
                                    msg = text_val
                                    break

                        if msg or author:
                            replies_data.append({
                                "Author": author or "Unknown",
                                "Msg": msg
                            })
                    if replies_data:
                        break
        except Exception as e:
            logger.debug(f"Error expanding replies: {e}")

        return replies_data

    async def _extract_comment_from_element(
        self,
        el,
        url: str,
        video_title: str
    ) -> tuple[Optional[YouTubeComment], Optional[str]]:
        """
        Extract author, msg, published time, and replies from a comment thread element.
        Returns: (YouTubeComment or None, published_time_str or None)
        """
        try:
            # 1. Extract Published Time and filter by max_months
            published_time = await self._extract_published_time(el)
            if self.max_months is not None and published_time:
                if not is_within_time_limit(published_time, max_months=self.max_months):
                    logger.debug(f"Skipping comment published '{published_time}' (older than {self.max_months} months)")
                    return None, published_time

            # 2. Extract Author
            author = ""
            for a_sel in COMMENT_AUTHOR_SELECTORS:
                try:
                    a_loc = el.locator(a_sel).first
                    if await a_loc.is_visible(timeout=250):
                        author_cand = (await a_loc.inner_text()).strip()
                        if author_cand:
                            author = author_cand
                            break
                except Exception:
                    continue

            # Fallback: extract author handle from href
            if not author:
                try:
                    href_el = el.locator('a[href*="/@"], a#author-text').first
                    if await href_el.count() > 0:
                        href_val = await href_el.get_attribute("href")
                        if href_val and "/@" in href_val:
                            author = "@" + href_val.split("/@")[-1].split("/")[0].split("?")[0]
                        else:
                            txt = await href_el.text_content()
                            if txt and txt.strip():
                                author = txt.strip()
                except Exception:
                    pass

            # 3. Extract Comment Message
            # Primary: <span class="ytAttributedStringHost ytAttributedStringWhiteSpacePreWrap" dir="auto" role="text">
            msg = ""
            for m_sel in COMMENT_MSG_SELECTORS:
                try:
                    m_loc = el.locator(m_sel).first
                    if await m_loc.is_visible(timeout=300):
                        msg_cand = (await m_loc.inner_text()).strip()
                        if msg_cand and not msg_cand.startswith("Pinned by") and not msg_cand.startswith("Fijado por"):
                            msg = msg_cand
                            break
                except Exception:
                    continue

            if not msg and not author:
                return None, published_time

            # 4. Extract Replies if requested
            replies: List[Dict[str, Any]] = []
            if self.expand_replies:
                replies = await self._extract_replies_for_thread(el)

            comment_obj = YouTubeComment(
                URL=url,
                Title=video_title,
                Video_Title=video_title,
                Author=author or "Unknown Author",
                Msg=msg,
                Reply=replies
            )
            return comment_obj, published_time

        except Exception as e:
            logger.debug(f"Failed to extract single comment: {e}")
            return None, None

    async def scrape_async(
        self,
        url: str,
        max_comments: Optional[int] = 100,
        sort_override: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Scrapes YouTube comments asynchronously using Playwright with date filtering.
        
        Args:
            url: YouTube video URL.
            max_comments: Maximum number of comments to collect (None for all).
            sort_override: 'newest', 'top', or None (auto > 500).
        
        Returns:
            List of comment dictionaries conforming strictly to schema.
        """
        logger.info(f"Starting YouTube comments scraper for URL: {url} (max_months={self.max_months})")

        async with async_playwright() as pw:
            browser: Browser = await pw.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-infobars",
                    "--lang=en-US,en"
                ]
            )

            context: BrowserContext = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="en-US"
            )

            page: Page = await context.new_page()
            page.set_default_timeout(self.timeout_ms)

            try:
                # 1. Open YouTube URL
                logger.info(f"Navigating to {url}...")
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                # Handle cookie/GDPR consent
                await self._handle_consent(page)

                # 2. Extract Video Title
                video_title = await self._get_video_title(page)
                logger.info(f"Video Title: {video_title}")

                # 3. Extract Comment Count from <h2 id="count"...>
                comment_count = await self._extract_comment_count(page)
                logger.info(f"Extracted Total Comments Count: {comment_count}")

                # Check min comments threshold (e.g. > 100)
                if self.min_comments_threshold is not None and comment_count > 0 and comment_count <= self.min_comments_threshold:
                    logger.info(f"Comment count ({comment_count}) <= threshold ({self.min_comments_threshold}). Bypassing video.")
                    return []

                # 4. Check if comments count > 500 or sort_override requested
                should_sort_newest = False
                if sort_override:
                    should_sort_newest = (sort_override.lower() == "newest")
                else:
                    should_sort_newest = (comment_count > self.sort_threshold)

                if should_sort_newest:
                    logger.info(f"Comment count ({comment_count}) > {self.sort_threshold} (or override). Switching sort to 'Newest'...")
                    sorted_ok = await self._sort_by_newest(page)
                    if sorted_ok:
                        logger.info("Successfully switched sort order to Newest.")
                    else:
                        logger.warning("Sort order switch failed or not available.")

                # 5. Collect comments from contents container
                collected_comments: List[YouTubeComment] = []
                seen_signatures: Set[str] = set()

                scroll_attempts = 0
                no_new_comments_count = 0
                last_collected_count = 0
                consecutive_old_comments = 0

                logger.info(f"Collecting comments (filtering comments within <= {self.max_months} months)...")

                while scroll_attempts < self.max_scroll_attempts:
                    comment_elements = []
                    for thread_sel in COMMENT_THREAD_SELECTORS:
                        try:
                            found = await page.locator(thread_sel).all()
                            if found:
                                comment_elements = found
                                break
                        except Exception:
                            continue

                    if not comment_elements:
                        for container_sel in COMMENTS_CONTAINER_SELECTORS:
                            try:
                                container = page.locator(container_sel).first
                                if await container.is_visible(timeout=500):
                                    comment_elements = await container.locator("ytd-comment-thread-renderer, ytd-comment-view-model").all()
                                    if comment_elements:
                                        break
                            except Exception:
                                continue

                    for el in comment_elements:
                        comment_obj, pub_time = await self._extract_comment_from_element(el, url, video_title)
                        
                        # Check date limit for early stopping in newest-first sort
                        if self.max_months is not None and pub_time:
                            if not is_within_time_limit(pub_time, max_months=self.max_months):
                                consecutive_old_comments += 1
                                # If sorting by newest and we hit 5 old comments in a row, all further comments are old
                                if should_sort_newest and consecutive_old_comments >= 5:
                                    logger.info(f"Encountered consecutive comments older than {self.max_months} months in newest-first order. Ending collection.")
                                    break
                            else:
                                consecutive_old_comments = 0

                        if comment_obj and comment_obj.Msg:
                            sig = f"{comment_obj.Author}:::{comment_obj.Msg[:120]}"
                            if sig not in seen_signatures:
                                seen_signatures.add(sig)
                                collected_comments.append(comment_obj)

                                if max_comments and len(collected_comments) >= max_comments:
                                    logger.info(f"Reached requested max_comments ({max_comments}).")
                                    break

                    if should_sort_newest and consecutive_old_comments >= 5:
                        break

                    if max_comments and len(collected_comments) >= max_comments:
                        break

                    # Check progress
                    if len(collected_comments) == last_collected_count:
                        no_new_comments_count += 1
                        if no_new_comments_count >= 5:
                            logger.info("No new comments loaded after 5 consecutive scrolls. Ending collection.")
                            break
                    else:
                        no_new_comments_count = 0
                        last_collected_count = len(collected_comments)

                    # Scroll down
                    await page.evaluate("window.scrollBy(0, 1200);")
                    await page.wait_for_timeout(self.scroll_pause_ms)
                    scroll_attempts += 1

                # In-browser DOM extraction fallback if needed
                if not collected_comments:
                    logger.info("Attempting in-browser DOM extraction fallback...")
                    raw_extracted = await page.evaluate('''() => {
                        const results = [];
                        const items = document.querySelectorAll('ytd-comment-thread-renderer, ytd-comment-view-model');
                        for (const item of items) {
                            const authorEl = item.querySelector('#author-text, a#author-text, #header-author a#author-text, span.ytd-comment-view-model');
                            const msgEl = item.querySelector('#content-text, span.ytAttributedStringHost, yt-attributed-string#content-text');
                            const timeEl = item.querySelector('#published-time-text a, #published-time-text');
                            const author = authorEl ? authorEl.textContent.trim() : 'Unknown Author';
                            const msg = msgEl ? msgEl.textContent.trim() : '';
                            const timeText = timeEl ? timeEl.textContent.trim() : '';
                            if (msg && !msg.startsWith('Pinned by') && !msg.startsWith('Fijado por')) {
                                results.push({ author, msg, timeText });
                            }
                        }
                        return results;
                    }''')
                    for item in raw_extracted:
                        pub_time = item.get("timeText", "")
                        if self.max_months is not None and pub_time:
                            if not is_within_time_limit(pub_time, max_months=self.max_months):
                                continue

                        c_obj = YouTubeComment(
                            URL=url,
                            Title=video_title,
                            Video_Title=video_title,
                            Author=item.get("author", "Unknown Author"),
                            Msg=item.get("msg", ""),
                            Reply=[]
                        )
                        sig = f"{c_obj.Author}:::{c_obj.Msg[:120]}"
                        if sig not in seen_signatures:
                            seen_signatures.add(sig)
                            collected_comments.append(c_obj)
                            if max_comments and len(collected_comments) >= max_comments:
                                break

                # Convert to dict and validate schema
                result_dicts = [c.to_dict() for c in collected_comments]
                validate_comments_data(result_dicts)
                logger.info(f"Successfully collected and validated {len(result_dicts)} comments.")
                return result_dicts

            finally:
                await context.close()
                await browser.close()

    def scrape(
        self,
        url: str,
        max_comments: Optional[int] = 100,
        sort_override: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Synchronous wrapper for scrape_async."""
        return asyncio.run(self.scrape_async(url, max_comments=max_comments, sort_override=sort_override))


def scrape_youtube_comments(
    url: str,
    max_comments: Optional[int] = 100,
    headless: bool = True,
    sort_override: Optional[str] = None,
    expand_replies: bool = False,
    max_months: Optional[int] = 6
) -> List[Dict[str, Any]]:
    """Helper function to scrape comments from a YouTube video URL with date filtering."""
    scraper = YouTubeCommentScraper(
        headless=headless,
        expand_replies=expand_replies,
        max_months=max_months
    )
    return scraper.scrape(url=url, max_comments=max_comments, sort_override=sort_override)
