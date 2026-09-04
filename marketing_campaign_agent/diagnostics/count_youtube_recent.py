"""Bounded read-only date-window audit; never assumes one old thread ends a page."""

import datetime
import json
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from marketing_campaign_agent.tools.youtube_api_tool import _get_api_key


def main():
    key = _get_api_key()
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoffs = {"90_days": now - datetime.timedelta(days=90),
               "current_code_91_5_days": now - datetime.timedelta(days=91.5)}
    counts = dict.fromkeys(cutoffs, 0)
    recent = []
    pages = []
    seen = set()
    token = ""
    old_pages = 0
    stop_reason = "diagnostic_page_limit"
    for page in range(10):
        params = {"key": key, "videoId": "W5ACjyQuEf0", "part": "snippet",
                  "order": "time", "maxResults": 100, "textFormat": "plainText"}
        if token:
            params["pageToken"] = token
        url = "https://www.googleapis.com/youtube/v3/commentThreads?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                data = json.loads(response.read())
        except Exception as exc:
            raise SystemExit(f"REQUEST_ERROR {type(exc).__name__}") from None
        page_counts = dict.fromkeys(cutoffs, 0)
        dates = []
        for item in data.get("items", []):
            comment = item["snippet"]["topLevelComment"]
            if comment["id"] in seen:
                continue
            seen.add(comment["id"])
            snippet = comment["snippet"]
            published = datetime.datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
            dates.append(snippet["publishedAt"])
            for window, cutoff in cutoffs.items():
                if cutoff <= published <= now:
                    counts[window] += 1
                    page_counts[window] += 1
            if min(cutoffs.values()) <= published <= now:
                recent.append({"id": comment["id"], "publishedAt": snippet["publishedAt"],
                               "updatedAt": snippet.get("updatedAt"),
                               "author": snippet.get("authorDisplayName"),
                               "text": snippet.get("textOriginal", snippet.get("textDisplay"))})
        summary = {"page": page + 1, "items": len(data.get("items", [])), "recent": page_counts,
                   "newest": max(dates) if dates else None, "oldest": min(dates) if dates else None}
        pages.append(summary)
        print("PAGE", json.dumps(summary), flush=True)
        token = data.get("nextPageToken", "")
        if not token:
            stop_reason = "api_exhausted"
            break
        old_pages = old_pages + 1 if page_counts["current_code_91_5_days"] == 0 else 0
        if old_pages == 2:
            stop_reason = "two_consecutive_pages_outside_window"
            break
    result = {"fetched_at": now.isoformat(), "cutoffs": {k: v.isoformat() for k, v in cutoffs.items()},
              "counts": counts, "pages": pages, "stop_reason": stop_reason,
              "api_exhausted": not bool(token), "comments": recent}
    Path(__file__).with_name("youtube_W5ACjyQuEf0_recent_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("COUNTS", json.dumps(counts), "STOP_REASON", stop_reason, flush=True)


if __name__ == "__main__":
    main()
