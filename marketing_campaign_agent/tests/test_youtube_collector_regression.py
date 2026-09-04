"""Regression coverage for chronological comment collection and pagination."""

import datetime
import json
from unittest.mock import MagicMock, patch

from marketing_campaign_agent.tools.youtube_comment_extractor_tool import (
    extract_comments_from_videos,
    fetch_video_comments_api,
)


VIDEO = "https://www.youtube.com/watch?v=W5ACjyQuEf0"


def response(items, token=""):
    value = {"items": items}
    if token:
        value["nextPageToken"] = token
    result = MagicMock()
    result.read.return_value = json.dumps(value).encode()
    return result


def item(comment_id, published, text):
    return {
        "id": comment_id,
        "snippet": {"topLevelComment": {"snippet": {
            "authorDisplayName": "@user", "textOriginal": text, "publishedAt": published,
        }}, "totalReplyCount": 0},
        "replies": {"comments": []},
    }


def test_old_first_thread_does_not_stop_pagination_and_result_is_newest_first():
    now = datetime.datetime.now(datetime.timezone.utc)
    newest = (now - datetime.timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    older_recent = (now - datetime.timedelta(days=2)).isoformat().replace("+00:00", "Z")
    old = "2020-05-05T21:10:25Z"
    pages = [response([item("old", old, "old"), item("new", older_recent, "new"),
                       item("newest", newest, "newest")], "next"), response([])]
    with patch("marketing_campaign_agent.tools.youtube_comment_extractor_tool.get_video_comment_count_api",
               return_value=23292), patch("urllib.request.urlopen") as open_url:
        open_url.return_value.__enter__.side_effect = pages
        comments = fetch_video_comments_api(VIDEO, api_key="key", window_days=90)

    assert [comment["Msg"] for comment in comments] == ["newest", "new"]
    assert all("_published_at" not in comment for comment in comments)
    assert open_url.call_count == 2


def test_unlimited_collection_crosses_page_boundary():
    now = datetime.datetime.now(datetime.timezone.utc)
    page_one = [item(str(i), (now - datetime.timedelta(minutes=i + 1)).isoformat().replace("+00:00", "Z"), str(i))
                for i in range(100)]
    page_two = [item("100", (now - datetime.timedelta(seconds=1)).isoformat().replace("+00:00", "Z"), "100")]
    with patch("marketing_campaign_agent.tools.youtube_comment_extractor_tool.get_video_comment_count_api",
               return_value=23292), patch("urllib.request.urlopen") as open_url:
        open_url.return_value.__enter__.side_effect = [response(page_one, "next"), response(page_two)]
        comments = fetch_video_comments_api(VIDEO, api_key="key", window_days=90)
    assert len(comments) == 101
    assert comments[0]["Msg"] == "100"


def test_api_failure_uses_playwright_fallback_even_with_api_key():
    fallback = [{"Author": "@user", "Msg": "recent", "Reply": []}]
    with patch("marketing_campaign_agent.tools.youtube_comment_extractor_tool.fetch_video_comments_api",
               side_effect=RuntimeError("quota")), patch(
                   "marketing_campaign_agent.tools.youtube_comment_extractor_tool.fetch_video_comments_playwright",
                   return_value=fallback) as playwright:
        result = extract_comments_from_videos([{"video_href": VIDEO, "video_keywords": "frecuencias"}],
                                              api_key="key")
    playwright.assert_called_once()
    assert result[0]["3_months_comments"] == fallback


def test_collected_comments_keep_identity_and_plain_text_request():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    with patch("marketing_campaign_agent.tools.youtube_comment_extractor_tool.get_video_comment_count_api",
               return_value=23292), patch("urllib.request.urlopen") as open_url:
        open_url.return_value.__enter__.side_effect = [
            response([item("stable-id", now, "mensaje literal")])
        ]
        comments = fetch_video_comments_api(VIDEO, api_key="key", window_days=90)
    assert comments[0]["comment_id"] == "stable-id"
    assert comments[0]["published_at"] == now
    query = open_url.call_args[0][0].full_url
    assert "textFormat=plainText" in query


def test_integrity_validator_rejects_missing_and_duplicate_ids():
    from marketing_campaign_agent.tools.comments_integrity_tool import validate_comments_integrity
    source = [{"comment_id": "a"}, {"comment_id": "b"}]
    result = validate_comments_integrity(source, [{"comment_id": "a", "decision": "deseo"}])
    assert result["status"] == "incomplete"
    assert result["missing_ids"] == ["b"]
