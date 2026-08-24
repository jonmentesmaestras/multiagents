"""Command line interface for YouTube Comments Collector."""

import argparse
import sys
import logging
from typing import Optional
from .scraper import YouTubeCommentScraper
from .exporter import export_comments_to_json, dump_comments_json_string


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    )


def main(args: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="YouTube Comments Collector using Playwright and Python with date filtering."
    )
    parser.add_argument(
        "url",
        type=str,
        help="YouTube video URL (e.g. https://www.youtube.com/watch?v=...)"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output JSON file path (e.g. comments.json). If omitted, prints to stdout."
    )
    parser.add_argument(
        "-m", "--max-comments",
        type=int,
        default=100,
        help="Maximum number of comments to extract (default: 100). Pass 0 for unlimited."
    )
    parser.add_argument(
        "--max-months",
        type=int,
        default=6,
        help="Maximum age of comments in months to collect (default: 6). Older comments (>=7 months) are excluded. Set to 0 or negative for no time limit."
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser in visible (headed) mode."
    )
    parser.add_argument(
        "--expand-replies",
        action="store_true",
        help="Expand comment reply threads and extract replies."
    )
    parser.add_argument(
        "--sort",
        type=str,
        choices=["auto", "newest", "top"],
        default="auto",
        help="Sort strategy. 'auto' switches to newest if >500 comments."
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=500,
        help="Comment count threshold to trigger 'Newest' sort in auto mode (default: 500)."
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable detailed debug logging."
    )

    parsed = parser.parse_args(args)
    setup_logging(parsed.verbose)

    max_comments = None if parsed.max_comments == 0 else parsed.max_comments
    sort_override = None if parsed.sort == "auto" else parsed.sort
    max_months = None if parsed.max_months <= 0 else parsed.max_months

    scraper = YouTubeCommentScraper(
        headless=not parsed.no_headless,
        expand_replies=parsed.expand_replies,
        sort_threshold=parsed.threshold,
        max_months=max_months
    )

    try:
        comments = scraper.scrape(
            url=parsed.url,
            max_comments=max_comments,
            sort_override=sort_override
        )

        if parsed.output:
            out_file = export_comments_to_json(comments, parsed.output)
            print(f"[SUCCESS] Saved {len(comments)} comments to {out_file}", file=sys.stderr)
        else:
            json_str = dump_comments_json_string(comments)
            print(json_str)

        return 0
    except Exception as e:
        logging.error(f"Scraping failed: {e}", exc_info=parsed.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
