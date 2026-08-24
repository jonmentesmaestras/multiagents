import pytest
import asyncio
from pathlib import Path
from youtube_scraper.scraper import YouTubeCommentScraper


MOCK_HTML_LESS_THAN_500 = """<!DOCTYPE html>
<html>
<head>
    <title>Small Video Demo - YouTube</title>
</head>
<body>
    <h1 class="style-scope ytd-watch-metadata">
        <yt-formatted-string>Small Video Demo</yt-formatted-string>
    </h1>

    <ytd-comments-header-renderer class="style-scope">
        <h2 id="count" class="style-scope ytd-comments-header-renderer">
            <yt-formatted-string class="count-text style-scope ytd-comments-header-renderer">
                <span dir="auto" class="style-scope yt-formatted-string">4</span>
                <span dir="auto" class="style-scope yt-formatted-string"> Comments</span>
            </yt-formatted-string>
        </h2>
        <div id="sort-menu">
            <div id="icon-label" class="style-scope yt-dropdown-menu">Sort by</div>
        </div>
    </ytd-comments-header-renderer>

    <div id="contents" class="style-scope ytd-item-section-renderer style-scope ytd-item-section-renderer">
        <ytd-comment-thread-renderer class="style-scope ytd-item-section-renderer">
            <div id="header-author">
                <a id="author-text" href="/@alice"><span>@alice</span></a>
                <span dir="auto" id="published-time-text" class="style-scope ytd-comment-view-model">
                    <a class="yt-simple-endpoint style-scope ytd-comment-view-model" href="/watch?v=1&lc=c1">
                        2 days ago
                    </a>
                </span>
            </div>
            <div id="content-text">
                <span class="ytAttributedStringHost ytAttributedStringWhiteSpacePreWrap" dir="auto" role="text" style="">First comment here!</span>
            </div>
        </ytd-comment-thread-renderer>

        <ytd-comment-thread-renderer class="style-scope ytd-item-section-renderer">
            <div id="header-author">
                <a id="author-text" href="/@bob"><span>@bob</span></a>
                <span dir="auto" id="published-time-text" class="style-scope ytd-comment-view-model">
                    <a class="yt-simple-endpoint style-scope ytd-comment-view-model" href="/watch?v=1&lc=c2">
                        6 months ago
                    </a>
                </span>
            </div>
            <div id="content-text">
                <span class="ytAttributedStringHost ytAttributedStringWhiteSpacePreWrap" dir="auto" role="text" style="">Second comment within 6 months!</span>
            </div>
        </ytd-comment-thread-renderer>

        <ytd-comment-thread-renderer class="style-scope ytd-item-section-renderer">
            <div id="header-author">
                <a id="author-text" href="/@old_user"><span>@old_user</span></a>
                <span dir="auto" id="published-time-text" class="style-scope ytd-comment-view-model">
                    <a class="yt-simple-endpoint style-scope ytd-comment-view-model" href="/watch?v=1&lc=c3">
                        7 months ago
                    </a>
                </span>
            </div>
            <div id="content-text">
                <span class="ytAttributedStringHost ytAttributedStringWhiteSpacePreWrap" dir="auto" role="text" style="">Old comment that should be excluded</span>
            </div>
        </ytd-comment-thread-renderer>

        <ytd-comment-thread-renderer class="style-scope ytd-item-section-renderer">
            <div id="header-author">
                <a id="author-text" href="/@ancient_user"><span>@ancient_user</span></a>
                <span dir="auto" id="published-time-text" class="style-scope ytd-comment-view-model">
                    <a class="yt-simple-endpoint style-scope ytd-comment-view-model" href="/watch?v=1&lc=c4">
                        1 year ago
                    </a>
                </span>
            </div>
            <div id="content-text">
                <span class="ytAttributedStringHost ytAttributedStringWhiteSpacePreWrap" dir="auto" role="text" style="">Ancient comment</span>
            </div>
        </ytd-comment-thread-renderer>
    </div>
</body>
</html>
"""


MOCK_HTML_GREATER_THAN_500 = """<!DOCTYPE html>
<html>
<head>
    <title>Popular Video Demo - YouTube</title>
</head>
<body>
    <h1 class="style-scope ytd-watch-metadata">
        <yt-formatted-string>Popular Video Demo</yt-formatted-string>
    </h1>

    <ytd-comments-header-renderer class="style-scope">
        <h2 id="count" class="style-scope ytd-comments-header-renderer">
            <yt-formatted-string class="count-text style-scope ytd-comments-header-renderer">
                <span dir="auto" class="style-scope yt-formatted-string">1,250</span>
                <span dir="auto" class="style-scope yt-formatted-string"> Comments</span>
            </yt-formatted-string>
        </h2>
        <div id="sort-menu">
            <div id="icon-label" class="style-scope yt-dropdown-menu" onclick="document.getElementById('sort-options').style.display='block'">Sort by</div>
            <div id="sort-options" style="display:none;">
                <div class="item style-scope yt-dropdown-menu" id="sort-top">Top comments</div>
                <div class="item style-scope yt-dropdown-menu" id="sort-newest" onclick="window.sortClicked = true;">Newest first</div>
            </div>
        </div>
    </ytd-comments-header-renderer>

    <div id="contents" class="style-scope ytd-item-section-renderer style-scope ytd-item-section-renderer">
        <ytd-comment-thread-renderer class="style-scope ytd-item-section-renderer">
            <div id="header-author">
                <a id="author-text" href="/@charlie"><span>@charlie</span></a>
                <span dir="auto" id="published-time-text" class="style-scope ytd-comment-view-model">
                    <a class="yt-simple-endpoint style-scope ytd-comment-view-model" href="/watch?v=2&lc=c1">
                        3 weeks ago
                    </a>
                </span>
            </div>
            <div id="content-text">
                <span class="ytAttributedStringHost ytAttributedStringWhiteSpacePreWrap" dir="auto" role="text" style="">Newest comment parsed!</span>
            </div>
        </ytd-comment-thread-renderer>

        <ytd-comment-thread-renderer class="style-scope ytd-item-section-renderer">
            <div id="header-author">
                <a id="author-text" href="/@dave"><span>@dave</span></a>
                <span dir="auto" id="published-time-text" class="style-scope ytd-comment-view-model">
                    <a class="yt-simple-endpoint style-scope ytd-comment-view-model" href="/watch?v=2&lc=c2">
                        8 months ago
                    </a>
                </span>
            </div>
            <div id="content-text">
                <span class="ytAttributedStringHost ytAttributedStringWhiteSpacePreWrap" dir="auto" role="text" style="">Older comment (8 months)</span>
            </div>
        </ytd-comment-thread-renderer>
    </div>
</body>
</html>
"""


def test_mock_scraper_date_filtering(tmp_path):
    mock_file = tmp_path / "small_video.html"
    mock_file.write_text(MOCK_HTML_LESS_THAN_500, encoding="utf-8")
    file_url = f"file:///{mock_file.as_posix()}"

    # Scraper with default max_months=6
    scraper = YouTubeCommentScraper(headless=True, scroll_pause_ms=200, max_scroll_attempts=2, max_months=6)
    comments = asyncio.run(scraper.scrape_async(file_url, max_comments=10))

    # Should only contain comments from 2 days ago and 6 months ago (2 comments)
    # Comments from 7 months ago and 1 year ago should be excluded!
    assert len(comments) == 2
    authors = [c["Author"] for c in comments]
    assert "@alice" in authors
    assert "@bob" in authors
    assert "@old_user" not in authors
    assert "@ancient_user" not in authors

    assert comments[0]["Author"] == "@alice"
    assert comments[0]["Msg"] == "First comment here!"
    assert comments[0]["Title"] == "Small Video Demo"
    assert comments[0]["Video Title"] == "Small Video Demo"
    assert comments[0]["URL"] == file_url
    assert isinstance(comments[0]["Reply"], list)

    assert comments[1]["Author"] == "@bob"
    assert comments[1]["Msg"] == "Second comment within 6 months!"


def test_mock_scraper_large_count_triggers_sort_and_date_filters(tmp_path):
    mock_file = tmp_path / "large_video.html"
    mock_file.write_text(MOCK_HTML_GREATER_THAN_500, encoding="utf-8")
    file_url = f"file:///{mock_file.as_posix()}"

    scraper = YouTubeCommentScraper(
        headless=True,
        scroll_pause_ms=200,
        max_scroll_attempts=2,
        sort_threshold=500,
        max_months=6
    )
    comments = asyncio.run(scraper.scrape_async(file_url, max_comments=10))

    # Should collect @charlie (3 weeks ago) and exclude @dave (8 months ago)
    assert len(comments) == 1
    assert comments[0]["Author"] == "@charlie"
    assert comments[0]["Msg"] == "Newest comment parsed!"
    assert comments[0]["Title"] == "Popular Video Demo"
    assert comments[0]["Video Title"] == "Popular Video Demo"
