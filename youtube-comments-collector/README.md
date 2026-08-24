# YouTube Comments Collector (Playwright + Python)

A robust, high-performance web scraper built with Python and Playwright to extract comments and replies from YouTube videos with automatic sorting, relative date filtering, multi-locale parsing, and JSON schema compliance.

---

## Features

- **Automated Workflow**:
  1. Opens any YouTube video URL using Playwright Chromium.
  2. Dismisses cookie / GDPR consent dialogs automatically.
  3. Extracts video title and scrolls to load comments.
  4. Locates `<h2 id="count" class="style-scope ytd-comments-header-renderer">` and parses the total comment count.
  5. **Auto-sort threshold**: If total comments > 500 (or custom threshold), clicks `<div id="icon-label" class="style-scope yt-dropdown-menu">Sort by</div>` and selects `"Newest first"`.
  6. **Date Filtering (<= 6 months)**: Checks the published time at `<span dir="auto" id="published-time-text" class="style-scope ytd-comment-view-model"> <a class="yt-simple-endpoint style-scope ytd-comment-view-model" href="...">...</a> </span>`. Only comments published within the last 6 months (up to the most recent date) are collected. Comments published 7 months or older (e.g. 7 months ago, 1 year ago, etc.) are excluded.
  7. Locates comments in `<div id="contents" class="style-scope ytd-item-section-renderer">` and extracts text from `<span class="ytAttributedStringHost ytAttributedStringWhiteSpacePreWrap" dir="auto" role="text">` (with robust fallbacks).
  8. Supports extracting nested replies (`--expand-replies`).
  9. Strictly validates output against JSON Schema Draft-07.
- **Resilient Selectors**: Multi-layer fallback strategy covering all modern YouTube DOM variants and locales.
- **Dual API**: Use via interactive CLI or directly as a Python library (`async` & `sync`).

---

## JSON Output Schema

Output conforms strictly to the requested schema:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "array",
  "items": {
    "type": "object",
    "required": ["URL", "Title", "Video Title", "Author", "Msg", "Reply"],
    "properties": {
      "URL": { "type": "string" },
      "Title": { "type": "string" },
      "Video Title": { "type": "string" },
      "Author": { "type": "string" },
      "Msg": { "type": "string" },
      "Reply": {
        "type": "array",
        "items": {}
      }
    }
  }
}
```

### Example JSON Output

```json
[
  {
    "URL": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "Title": "Me at the zoo",
    "Video Title": "Me at the zoo",
    "Author": "@SanDiegoZoo",
    "Msg": "We're so honored that the first ever YouTube video was filmed here!",
    "Reply": []
  },
  {
    "URL": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "Title": "Me at the zoo",
    "Video Title": "Me at the zoo",
    "Author": "@samra.123.12A",
    "Msg": "We're waiting for a new video... after 21 years.",
    "Reply": []
  }
]
```

---

## Installation

1. **Clone repository and enter directory**:
   ```bash
   cd youtube-comments-collector
   ```

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Playwright Chromium browser**:
   ```bash
   python -m playwright install chromium
   ```

---

## CLI Usage

### Basic Usage (Collect recent comments <= 6 months)
```bash
python main.py "https://www.youtube.com/watch?v=jNQXAC9IVRw" -m 20
```

### Save to JSON file
```bash
python main.py "https://www.youtube.com/watch?v=jNQXAC9IVRw" -o comments.json -m 50
```

### Custom Date Filter (e.g. up to 3 months or no limit)
```bash
# Only comments from the last 3 months
python main.py "https://www.youtube.com/watch?v=jNQXAC9IVRw" --max-months 3

# No time limit (collect all dates)
python main.py "https://www.youtube.com/watch?v=jNQXAC9IVRw" --max-months 0
```

### CLI Arguments & Options

| Option | Description | Default |
|---|---|---|
| `url` | Target YouTube video URL | *(Required)* |
| `-o, --output` | Path to output JSON file (if omitted, writes to stdout) | `None` |
| `-m, --max-comments` | Maximum number of comments to collect (0 for all) | `100` |
| `--max-months` | Maximum age of comments in months (excludes >= 7 months) | `6` |
| `--expand-replies` | Expand and extract nested comment replies | `False` |
| `--sort` | Sort mode: `auto` (>500 comments triggers newest), `newest`, `top` | `auto` |
| `--threshold` | Comment count threshold to switch to newest | `500` |
| `--no-headless` | Run browser in visible window | `False` (runs headless) |
| `-v, --verbose` | Enable detailed debug logs | `False` |

---

## Python API Usage

### Synchronous Usage
```python
from youtube_scraper import YouTubeCommentScraper, export_comments_to_json

scraper = YouTubeCommentScraper(
    headless=True,
    expand_replies=False,
    sort_threshold=500,
    max_months=6  # Only comments published within the last 6 months
)

comments = scraper.scrape(
    url="https://www.youtube.com/watch?v=jNQXAC9IVRw",
    max_comments=25
)

# Export to file
export_comments_to_json(comments, "output.json")
```

### Asynchronous Usage (`asyncio`)
```python
import asyncio
from youtube_scraper import YouTubeCommentScraper

async def main():
    scraper = YouTubeCommentScraper(headless=True, max_months=6)
    comments = await scraper.scrape_async(
        url="https://www.youtube.com/watch?v=jNQXAC9IVRw",
        max_comments=10
    )
    print(f"Collected {len(comments)} comments")

asyncio.run(main())
```

---

## Running Tests

Run the full test suite with pytest:

```bash
python -m pytest -v
```

Test suite coverage:
- `test_parser.py`: Comment count formatting (K/M shorthand, localized formats) and relative date parsing (seconds, minutes, hours, days, weeks, months, years, multilingual, <=6 vs >=7 months).
- `test_schema.py`: Strict JSON Schema Draft-07 compliance validation.
- `test_mock_scraper.py`: DOM parsing, `<500` vs `>500` sort switching, published-time filtering, and reply collection.
- `test_cli.py`: Command-line interface argument parsing, execution, date filtering, and file output.
