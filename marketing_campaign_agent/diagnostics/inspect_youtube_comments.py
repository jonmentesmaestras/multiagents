"""Read-only probe of the API ordering for the reported comment-collection bug."""

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
    if not key:
        raise SystemExit("NO_API_KEY")

    def get(endpoint, params):
        url = "https://www.googleapis.com/youtube/v3/" + endpoint + "?" + urllib.parse.urlencode(
            {**params, "key": key}
        )
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            error = json.loads(exc.read()).get("error", {})
            reasons = [item.get("reason") for item in error.get("errors", [])]
            raise SystemExit(f"HTTP_ERROR {exc.code}: {reasons}") from None
        except Exception as exc:
            # Avoid leaking an authenticated URL from exception representations.
            raise SystemExit(f"REQUEST_ERROR {type(exc).__name__}") from None

    stats = get("videos", {"part": "statistics", "id": "W5ACjyQuEf0"})
    print("STATS", json.dumps(stats, ensure_ascii=True))
    data = get("commentThreads", {
        "part": "snippet,replies", "videoId": "W5ACjyQuEf0", "maxResults": 50, "order": "time",
    })
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=91.5)
    print("NOW", now.isoformat(), "CUTOFF", cutoff.isoformat())
    print("ITEMS", len(data.get("items", [])), "HAS_NEXT", bool(data.get("nextPageToken")))
    counts = {"recent": 0, "old": 0}
    for i, item in enumerate(data.get("items", [])):
        snippet = item["snippet"]["topLevelComment"]["snippet"]
        recent = datetime.datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00")) >= cutoff
        counts["recent" if recent else "old"] += 1
        if i < 8 or not recent:
            print("COMMENT", json.dumps({
                "index": i, "id": item["id"], "publishedAt": snippet.get("publishedAt"),
                "updatedAt": snippet.get("updatedAt"), "recent": recent,
                "replyCount": item["snippet"].get("totalReplyCount"),
            }, ensure_ascii=True))
    print("COUNTS", counts)
    Path(__file__).with_name("youtube_W5ACjyQuEf0_first_page.json").write_text(json.dumps({
        "fetched_at": now.isoformat(), "stats": stats, "comments": data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
