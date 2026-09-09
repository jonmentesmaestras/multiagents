import json
from unittest.mock import MagicMock, patch

from marketing_campaign_agent.tools.youtube_api_tool import (
    search_and_collect_youtube_data, search_youtube_videos_api,
)


def _response(payload):
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    return response


def test_api_search_returns_metadata_needed_for_semantic_validation():
    search = {"items": [{"id": {"videoId": "abc123xyz89"}}]}
    details = {"items": [{
        "id": "abc123xyz89",
        "snippet": {
            "title": "Molde F1 para uñas",
            "description": "Tutorial de extensiones de uñas para manicuristas.",
            "channelTitle": "Academia Nail",
            "defaultLanguage": "es",
            "defaultAudioLanguage": "es-ES",
        },
        "statistics": {"viewCount": "250000"},
    }]}
    with patch("urllib.request.urlopen") as open_url:
        open_url.return_value.__enter__.side_effect = [_response(search), _response(details)]
        rows = search_youtube_videos_api("molde F1 uñas", min_views=0, api_key="key")
    assert rows[0]["video_description"].startswith("Tutorial de extensiones")
    assert rows[0]["channel_title"] == "Academia Nail"
    assert rows[0]["default_language"] == "es"
    assert rows[0]["audio_language"] == "es-ES"
    assert rows[0]["view_count"] == 250000
    assert rows[0]["comment_count"] is None
    assert rows[0]["published_at"] is None


def test_playwright_fallback_is_enriched_with_api_metadata():
    raw = [{
        "video_href": "https://www.youtube.com/watch?v=abc123xyz89&pp=test",
        "video_title": "Título parcial", "comment_count": None,
    }]
    details = {"items": [{
        "id": "abc123xyz89",
        "snippet": {
            "title": "Comunicación intuitiva con animales",
            "description": "Cómo entender las emociones y necesidades de tu mascota.",
            "channelTitle": "Animales en español", "defaultLanguage": "es",
            "defaultAudioLanguage": "es-ES", "publishedAt": "2026-01-01T00:00:00Z",
        },
        "statistics": {"viewCount": "292000", "commentCount": "1982"},
    }]}
    with patch("marketing_campaign_agent.tools.youtube_api_tool.search_youtube_videos_api",
               side_effect=RuntimeError("search unavailable")), \
            patch("marketing_campaign_agent.tools.youtube_api_tool.search_youtube_videos",
                  return_value=raw), patch("urllib.request.urlopen") as open_url:
        open_url.return_value.__enter__.return_value = _response(details)
        rows = search_and_collect_youtube_data("comunicación animal", api_key="key")
    assert rows[0]["comment_count"] == 1982
    assert rows[0]["view_count"] == 292000
    assert rows[0]["video_description"].startswith("Cómo entender")
    assert rows[0]["audio_language"] == "es-ES"
    assert rows[0]["metadata_status"] == "complete"
    assert rows[0]["search_source"] == "playwright_fallback"
