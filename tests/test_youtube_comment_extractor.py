"""Unit tests for YouTube Comment Extractor tool and agent."""

import datetime
import json
from unittest.mock import MagicMock, patch
import pytest
from google.adk.agents import LlmAgent

from marketing_campaign_agent.agent import (
    campaign_orchestrator,
    landing_page_research_agent,
    youtube_comment_extractor_agent,
    youtube_comments_analyzer_agent,
)
from marketing_campaign_agent.tools import (
    extract_comments_from_videos,
    fetch_video_comments_api,
)
from marketing_campaign_agent.tools.youtube_comment_extractor_tool import (
    _parse_videos_input,
)


class TestParseVideosInput:
    def test_list_of_dicts_with_video_href(self):
        videos = [
            {"video_keywords": "kw1", "video_title": "Title 1", "video_href": "https://www.youtube.com/watch?v=vid1", "video_views": "100K views"},
            {"video_keywords": "kw2", "video_title": "Title 2", "video_href": "https://www.youtube.com/watch?v=vid2", "video_views": "200K views"},
        ]
        parsed = _parse_videos_input(videos)
        assert parsed == ["https://www.youtube.com/watch?v=vid1", "https://www.youtube.com/watch?v=vid2"]

    def test_json_string_input(self):
        json_str = json.dumps([
            {"video_href": "https://www.youtube.com/watch?v=vid1"},
            {"video_href": "https://www.youtube.com/watch?v=vid2"},
        ])
        parsed = _parse_videos_input(json_str)
        assert parsed == ["https://www.youtube.com/watch?v=vid1", "https://www.youtube.com/watch?v=vid2"]

    def test_list_of_strings(self):
        urls = ["https://www.youtube.com/watch?v=vid1", "https://youtu.be/vid2"]
        parsed = _parse_videos_input(urls)
        assert parsed == urls

    def test_single_url_string(self):
        url = "https://www.youtube.com/watch?v=vid1"
        parsed = _parse_videos_input(url)
        assert parsed == [url]

    def test_empty_or_invalid_input(self):
        assert _parse_videos_input([]) == []
        assert _parse_videos_input("") == []
        assert _parse_videos_input(None) == []


class TestFetchVideoCommentsApi:
    @patch("urllib.request.urlopen")
    def test_fetch_comments_api_success(self, mock_urlopen):
        # Recent timestamp (< 6 months)
        recent_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)).isoformat()
        
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "snippet": {
                                "authorDisplayName": "@juan_perez",
                                "textDisplay": "Excelente explicación de ventas!",
                                "publishedAt": recent_date,
                            }
                        }
                    }
                }
            ]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        comments = fetch_video_comments_api(
            video_id_or_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            max_comments=10,
            max_months=6,
            order="time",
            api_key="fake_key",
        )

        assert len(comments) == 1
        assert comments[0]["user"] == "@juan_perez"
        assert comments[0]["comment"] == "Excelente explicación de ventas!"
        assert comments[0]["when"] == recent_date

    @patch("urllib.request.urlopen")
    def test_fetch_comments_api_filters_older_than_6_months(self, mock_urlopen):
        # Old timestamp (1 year ago)
        old_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=365)).isoformat()
        
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "snippet": {
                                "authorDisplayName": "@antiguo_user",
                                "textDisplay": "Comentario de hace un año",
                                "publishedAt": old_date,
                            }
                        }
                    }
                }
            ]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        comments = fetch_video_comments_api(
            video_id_or_url="dQw4w9WgXcQ",
            max_comments=10,
            max_months=6,
            order="time",
            api_key="fake_key",
        )

        # Older comments should be filtered out
        assert len(comments) == 0


class TestExtractCommentsFromVideos:
    @patch("marketing_campaign_agent.tools.youtube_comment_extractor_tool.fetch_video_comments_api")
    def test_extract_comments_from_video_list(self, mock_fetch_api):
        mock_fetch_api.return_value = [
            {"user": "@tester", "comment": "Gran video", "when": "2026-02-15T12:00:00Z"}
        ]

        input_videos = [
            {"video_keywords": "marketing", "video_title": "T1", "video_href": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "video_views": "1M views"}
        ]

        results = extract_comments_from_videos(input_videos, api_key="fake_key")

        assert len(results) == 1
        assert results[0]["video_href"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert len(results[0]["comments"]) == 1
        assert results[0]["comments"][0]["user"] == "@tester"
        assert results[0]["comments"][0]["comment"] == "Gran video"
        assert results[0]["comments"][0]["when"] == "2026-02-15T12:00:00Z"


class TestYoutubeCommentExtractorAgentConfig:
    def test_agent_configuration(self):
        assert isinstance(youtube_comment_extractor_agent, LlmAgent)
        assert youtube_comment_extractor_agent.name == "YoutubeCommentExtractor"
        assert youtube_comment_extractor_agent.output_key == "youtube_comments_extracted"
        assert youtube_comment_extractor_agent.tools is not None
        assert extract_comments_from_videos in youtube_comment_extractor_agent.tools

    def test_orchestrator_sub_agents_sequence(self):
        assert len(campaign_orchestrator.sub_agents) == 3
        assert campaign_orchestrator.sub_agents[0] is landing_page_research_agent
        assert campaign_orchestrator.sub_agents[1] is youtube_comments_analyzer_agent
        assert campaign_orchestrator.sub_agents[2] is youtube_comment_extractor_agent
