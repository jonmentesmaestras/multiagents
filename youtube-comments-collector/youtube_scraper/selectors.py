"""Centralized DOM selectors for YouTube comments scraping.
Matches user specified classes and provides resilient fallbacks.
"""

from typing import List

# Video title selectors
VIDEO_TITLE_SELECTORS: List[str] = [
    "h1.style-scope.ytd-watch-metadata yt-formatted-string",
    "h1.ytd-watch-metadata yt-formatted-string",
    "h1.title.style-scope.ytd-video-primary-info-renderer yt-formatted-string",
    "h1.ytd-video-primary-info-renderer",
    "h1 yt-formatted-string",
    "meta[name='title']",
    "title",
]

# Primary count selectors as requested:
# <h2 id="count" class="style-scope ytd-comments-header-renderer">
#   <yt-formatted-string class="count-text style-scope ytd-comments-header-renderer">
#     <span dir="auto" class="style-scope yt-formatted-string">4</span>
COUNT_HEADER_SELECTORS: List[str] = [
    'h2#count.style-scope.ytd-comments-header-renderer yt-formatted-string.count-text span.style-scope.yt-formatted-string',
    'h2#count.style-scope.ytd-comments-header-renderer yt-formatted-string.count-text',
    'h2#count yt-formatted-string.count-text',
    'h2#count.style-scope.ytd-comments-header-renderer',
    'ytd-comments-header-renderer #count yt-formatted-string',
    'ytd-comments-header-renderer #count',
    '#comments-header #count',
]

# Sort button selectors:
# <div id="icon-label" class="style-scope yt-dropdown-menu">Sort by</div>
SORT_DROPDOWN_BUTTON_SELECTORS: List[str] = [
    'div#icon-label.style-scope.yt-dropdown-menu',
    'ytd-comments-header-renderer #sort-menu tp-yt-paper-button',
    'yt-sort-filter-sub-menu-renderer #icon-label',
    '#sort-menu #icon-label',
    'yt-sort-filter-sub-menu-renderer',
    '#sort-menu tp-yt-paper-button',
]

# Sort option items (Newest first / Más recientes):
# <div class="item style-scope yt-dropdown-menu">...</div>
SORT_OPTION_NEWEST_SELECTORS: List[str] = [
    'div.item.style-scope.yt-dropdown-menu:nth-child(2)',
    'tp-yt-paper-listbox.style-scope.yt-dropdown-menu > a:nth-child(2)',
    'ytd-menu-service-item-renderer:has-text("Newest")',
    'ytd-menu-service-item-renderer:has-text("recientes")',
    'ytd-menu-service-item-renderer:nth-of-type(2)',
    'tp-yt-paper-listbox ytd-menu-service-item-renderer:nth-child(2)',
    'tp-yt-paper-item:has-text("Newest")',
    'tp-yt-paper-item:has-text("recientes")',
    'a.yt-dropdown-menu:nth-child(2)',
]

# Comments contents container:
# <div id="contents" class="style-scope ytd-item-section-renderer style-scope ytd-item-section-renderer">
COMMENTS_CONTAINER_SELECTORS: List[str] = [
    'div#contents.style-scope.ytd-item-section-renderer',
    'ytd-item-section-renderer#sections div#contents',
    'ytd-comments#comments div#contents',
    '#comments #contents',
]

# Individual comment thread renderer
COMMENT_THREAD_SELECTORS: List[str] = [
    'ytd-comment-thread-renderer',
    'ytd-comment-view-model',
]

# Comment message text selector:
# <span class="ytAttributedStringHost ytAttributedStringWhiteSpacePreWrap" dir="auto" role="text" style=""></span>
COMMENT_MSG_SELECTORS: List[str] = [
    '#content-text span.ytAttributedStringHost.ytAttributedStringWhiteSpacePreWrap[role="text"]',
    '#content-text span.ytAttributedStringHost.ytAttributedStringWhiteSpacePreWrap',
    '#content-text span.ytAttributedStringHost',
    'span.ytAttributedStringHost.ytAttributedStringWhiteSpacePreWrap[role="text"]',
    'span.ytAttributedStringHost.ytAttributedStringWhiteSpacePreWrap',
    '#expander #content-text',
    '#content-text span.yt-core-attributed-string',
    '#content-text yt-attributed-string',
    'yt-attributed-string#content-text',
    '#content-text',
    'div#content-text',
]

# Comment author selector:
COMMENT_AUTHOR_SELECTORS: List[str] = [
    '#header-author a#author-text span',
    '#header-author a#author-text',
    'a#author-text span',
    'a#author-text',
    '#header-author span.ytd-comment-view-model',
    'a[href*="/@"] span',
    'a[href*="/@"]',
    '#author-text',
    'span.ytd-comment-view-model',
]

# Published time selector:
# <span dir="auto" id="published-time-text" class="style-scope ytd-comment-view-model">
#   <a class="yt-simple-endpoint style-scope ytd-comment-view-model" href="...">6 months ago</a>
# </span>
PUBLISHED_TIME_SELECTORS: List[str] = [
    'span#published-time-text.style-scope.ytd-comment-view-model a.yt-simple-endpoint.style-scope.ytd-comment-view-model',
    'span#published-time-text.style-scope.ytd-comment-view-model a',
    'span#published-time-text a.yt-simple-endpoint',
    'span#published-time-text a',
    '#published-time-text a',
    'yt-formatted-string.published-time-text a',
    'a.yt-simple-endpoint[href*="lc="]',
    'span#published-time-text',
    '#published-time-text',
]

# Consent dialog buttons (to accept/dismiss GDPR/Cookie popups)
CONSENT_BUTTON_SELECTORS: List[str] = [
    'button[aria-label="Accept all"]',
    'button[aria-label="Aceptar todo"]',
    'button[aria-label="Accept the use of cookies and other data for the purposes described"]',
    'ytd-button-renderer button:has-text("Accept all")',
    'ytd-button-renderer button:has-text("Aceptar todo")',
    'button:has-text("Accept all")',
    'button:has-text("Aceptar todo")',
    'button:has-text("I agree")',
    'button:has-text("Agree")',
    'button:has-text("Accept")',
    'button:has-text("Acepto")',
]

# Replies selector
REPLIES_MORE_BUTTON_SELECTORS: List[str] = [
    '#replies ytd-button-renderer#more-replies button',
    '#more-replies button',
    'ytd-button-renderer#more-replies',
    '#replies button[aria-label*="repl"]',
    '#replies button[aria-label*="respuest"]',
]

REPLIES_CONTAINER_SELECTORS: List[str] = [
    '#replies ytd-comment-replies-renderer #contents ytd-comment-renderer',
    '#replies ytd-comment-renderer',
    '#replies ytd-comment-view-model',
]
