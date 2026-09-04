"""Unit tests for YouTube Comments Collector tool and agent."""

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
    youtube_comments_collector_agent,
)
from marketing_campaign_agent.tools import (
    collect_youtube_comments,
    extract_comments_from_videos,
    fetch_video_comments_api,
    get_video_comment_count_api,
)
from marketing_campaign_agent.tools.youtube_comment_extractor_tool import (
    _parse_video_entries,
    _parse_videos_input,
)


class TestParseVideoEntries:
    def test_list_of_dicts_with_video_href_and_keywords(self):
        videos = [
            {
                "video_keywords": "como hacer velas artesanales para vender",
                "video_title": "Las velas más lindas",
                "video_href": "https://www.youtube.com/watch?v=tPcRVA3CwdA",
                "video_views": "40.7M views",
            },
            {
                "video_keywords": "velas artesanales negocio",
                "video_title": "3 Ideas con VELAS",
                "video_href": "https://www.youtube.com/watch?v=upOHbEEw5J8",
                "video_views": "12.5M views",
            },
        ]
        parsed = _parse_video_entries(videos)
        assert len(parsed) == 2
        assert parsed[0]["video_href"] == "https://www.youtube.com/watch?v=tPcRVA3CwdA"
        assert parsed[0]["video_keywords"] == "como hacer velas artesanales para vender"
        assert parsed[1]["video_href"] == "https://www.youtube.com/watch?v=upOHbEEw5J8"
        assert parsed[1]["video_keywords"] == "velas artesanales negocio"

    def test_json_string_input(self):
        json_str = json.dumps([
            {
                "video_href": "https://www.youtube.com/watch?v=vid1",
                "video_keywords": "keyword 1",
            },
            {
                "video_href": "https://www.youtube.com/watch?v=vid2",
                "video_keywords": "keyword 2",
            },
        ])
        parsed = _parse_video_entries(json_str)
        assert len(parsed) == 2
        assert parsed[0]["video_href"] == "https://www.youtube.com/watch?v=vid1"
        assert parsed[0]["video_keywords"] == "keyword 1"

    def test_list_of_strings(self):
        urls = ["https://www.youtube.com/watch?v=vid1", "https://youtu.be/vid2"]
        parsed = _parse_video_entries(urls)
        assert len(parsed) == 2
        assert parsed[0]["video_href"] == "https://www.youtube.com/watch?v=vid1"
        assert parsed[1]["video_href"] == "https://www.youtube.com/watch?v=vid2"

    def test_single_url_string(self):
        url = "https://www.youtube.com/watch?v=vid1"
        parsed = _parse_video_entries(url)
        assert len(parsed) == 1
        assert parsed[0]["video_href"] == url

    def test_backward_compatible_parse_urls(self):
        urls = ["https://www.youtube.com/watch?v=vid1"]
        assert _parse_videos_input(urls) == urls


class TestGetVideoCommentCountApi:
    @patch("urllib.request.urlopen")
    def test_get_comment_count_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "items": [
                {
                    "statistics": {
                        "viewCount": "1000000",
                        "commentCount": "450",
                    }
                }
            ]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        count = get_video_comment_count_api("dQw4w9WgXcQ", api_key="fake_key")
        assert count == 450


class TestFetchVideoCommentsApi:
    @patch("marketing_campaign_agent.tools.youtube_comment_extractor_tool.get_video_comment_count_api")
    @patch("urllib.request.urlopen")
    def test_fetch_comments_api_success_above_threshold(self, mock_urlopen, mock_count):
        # Total comments > 100
        mock_count.return_value = 500

        # Recent timestamp (< 3 months)
        recent_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=15)).isoformat()

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "snippet": {
                                "authorDisplayName": "@rosahiselagonzalez9724",
                                "textDisplay": "A dónde se van los animalitos cuándo se mueren! Quiero volver a ver a mi perrito",
                                "publishedAt": recent_date,
                            }
                        }
                    },
                    "replies": {
                        "comments": [
                            {
                                "snippet": {
                                    "authorDisplayName": "@reply_user",
                                    "textDisplay": "Un abrazo fuerte!",
                                }
                            }
                        ]
                    },
                }
            ]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        comments = fetch_video_comments_api(
            video_id_or_url="https://www.youtube.com/watch?v=tPcRVA3CwdA",
            max_comments=10,
            max_months=3,
            min_comments_threshold=100,
            order="time",
            api_key="fake_key",
        )

        assert comments is not None
        assert len(comments) == 1
        assert comments[0]["Author"] == "@rosahiselagonzalez9724"
        assert "animalitos" in comments[0]["Msg"]
        assert len(comments[0]["Reply"]) == 1
        assert comments[0]["Reply"][0]["Author"] == "@reply_user"

    @patch("marketing_campaign_agent.tools.youtube_comment_extractor_tool.get_video_comment_count_api")
    def test_fetch_comments_api_bypasses_when_total_comments_under_threshold(self, mock_count):
        # Total comments <= 100 -> Should bypass (return None)
        mock_count.return_value = 45

        comments = fetch_video_comments_api(
            video_id_or_url="https://www.youtube.com/watch?v=low_comments_vid",
            min_comments_threshold=100,
            api_key="fake_key",
        )

        assert comments is None

    @patch("marketing_campaign_agent.tools.youtube_comment_extractor_tool.get_video_comment_count_api")
    @patch("urllib.request.urlopen")
    def test_fetch_comments_api_filters_older_than_3_months(self, mock_urlopen, mock_count):
        mock_count.return_value = 250

        # Old timestamp (> 3 months, e.g. 120 days)
        old_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=120)).isoformat()

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "snippet": {
                                "authorDisplayName": "@antiguo_user",
                                "textDisplay": "Comentario antiguo de hace 4 meses",
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
            max_months=3,
            min_comments_threshold=100,
            order="time",
            api_key="fake_key",
        )

        # Older comments should be filtered out
        assert comments == []


class TestExtractCommentsFromVideos:
    @patch("marketing_campaign_agent.tools.youtube_comment_extractor_tool.fetch_video_comments_api")
    def test_extract_comments_from_video_list_with_bypass(self, mock_fetch_api):
        # First video has >100 comments, second video is bypassed (<=100 comments)
        def side_effect(video_id_or_url, **kwargs):
            if "vid1" in video_id_or_url:
                return [
                    {
                        "Author": "@rosahiselagonzalez9724",
                        "Msg": "A dónde se van los animalitos cuándo se mueren! Quiero volver a ver a mi perrito",
                        "Reply": [],
                    }
                ]
            # Second video is bypassed
            return None

        mock_fetch_api.side_effect = side_effect

        input_videos = [
            {
                "video_keywords": "como hacer velas artesanales para vender",
                "video_title": "Velas 1",
                "video_href": "https://www.youtube.com/watch?v=vid1",
                "video_views": "40M views",
            },
            {
                "video_keywords": "como hacer velas artesanales para vender",
                "video_title": "Velas 2",
                "video_href": "https://www.youtube.com/watch?v=vid2_low",
                "video_views": "500K views",
            },
        ]

        results = extract_comments_from_videos(input_videos, api_key="fake_key")

        # Only video 1 is kept in results; video 2 was bypassed
        assert len(results) == 1
        assert results[0]["video_href"] == "https://www.youtube.com/watch?v=vid1"
        assert results[0]["video_keywords"] == "como hacer velas artesanales para vender"
        assert "3_months_comments" in results[0]
        assert len(results[0]["3_months_comments"]) == 1
        assert results[0]["3_months_comments"][0]["Author"] == "@rosahiselagonzalez9724"
        assert results[0]["3_months_comments"][0]["Reply"] == []


class TestYoutubeCommentsCollectorAgentConfig:
    def test_agent_configuration(self):
        assert isinstance(youtube_comments_collector_agent, LlmAgent)
        assert youtube_comments_collector_agent.name == "YoutubeCommentsCollector"
        assert youtube_comments_collector_agent.output_key == "youtube_comments_collected"
        assert youtube_comments_collector_agent.tools is not None
        assert extract_comments_from_videos in youtube_comments_collector_agent.tools

    def test_orchestrator_sub_agents_sequence(self):
        assert len(campaign_orchestrator.sub_agents) >= 3
        assert campaign_orchestrator.sub_agents[0] is landing_page_research_agent
        assert campaign_orchestrator.sub_agents[1] is youtube_comments_analyzer_agent
        assert campaign_orchestrator.sub_agents[2] is youtube_comments_collector_agent
