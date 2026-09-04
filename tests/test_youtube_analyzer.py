"""Unit tests for YouTube Data API tool, YouTube search tool, and YouTube Comments Analyzer Agent."""

import pytest
from google.adk.agents import LlmAgent

from marketing_campaign_agent.agent import (
    campaign_orchestrator,
    landing_page_research_agent,
    youtube_comments_analyzer_agent,
)
from marketing_campaign_agent.tools import (
    extract_video_id,
    format_view_count,
    parse_view_count,
    search_and_collect_youtube_data,
    search_youtube_videos,
    search_youtube_videos_api,
)


class TestParseViewCount:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("599K views", 599_000),
            ("1.2M views", 1_200_000),
            ("2.5M visualizaciones", 2_500_000),
            ("500K visualizaciones", 500_000),
            ("45K vistas", 45_000),
            ("100.000 visualizaciones", 100_000),
            ("120,450 views", 120_450),
            ("1.5B views", 1_500_000_000),
            ("1,2 M de visualizaciones", 1_200_000),
            ("95K", 95_000),
            ("100K", 100_000),
        ],
    )
    def test_view_count_parsing(self, text, expected):
        """Verify view counts in English and Spanish are parsed into accurate integers."""
        assert parse_view_count(text) == expected

    def test_empty_or_invalid_view_text(self):
        """Verify invalid or empty strings return None gracefully."""
        assert parse_view_count("") is None
        assert parse_view_count(None) is None
        assert parse_view_count("No views available") is None


class TestFormatViewCountAndExtractVideoId:
    @pytest.mark.parametrize(
        "views,expected",
        [
            (450_000, "450K"),
            (1_200_000, "1.2M"),
            (2_000_000, "2M"),
            (1_500_000_000, "1.5B"),
            (85_000, "85K"),
            (500, "500"),
        ],
    )
    def test_format_view_count(self, views, expected):
        """Verify numbers are formatted into clean K/M/B representation."""
        assert format_view_count(views) == expected

    @pytest.mark.parametrize(
        "url_or_id,expected_id",
        [
            ("https://www.youtube.com/watch?v=2n34P4K08qE", "2n34P4K08qE"),
            ("https://youtu.be/7M0qG5hXk9U", "7M0qG5hXk9U"),
            ("https://www.youtube.com/embed/5V9xQ2zM3kL", "5V9xQ2zM3kL"),
            ("2n34P4K08qE", "2n34P4K08qE"),
        ],
    )
    def test_extract_video_id(self, url_or_id, expected_id):
        """Verify 11-char video ID is extracted correctly from URLs."""
        assert extract_video_id(url_or_id) == expected_id


class TestYoutubeSearchToolArguments:
    def test_empty_keywords_returns_empty_list(self):
        """Verify calling tools with empty keyword list returns empty list."""
        assert search_youtube_videos([]) == []
        assert search_youtube_videos("") == []
        assert search_youtube_videos(None) == []
        assert search_youtube_videos_api([], api_key="dummy") == []
        assert search_youtube_videos_api("", api_key="dummy") == []


class TestYoutubeCommentsAnalyzerAgentConfig:
    def test_agent_type_and_name(self):
        """Verify youtube_comments_analyzer_agent is configured with expected name and type."""
        assert isinstance(youtube_comments_analyzer_agent, LlmAgent)
        assert youtube_comments_analyzer_agent.name == "YoutubeCommentsAnalyzer"

    def test_agent_output_key(self):
        """Verify output_key is configured as youtube_videos_research."""
        assert youtube_comments_analyzer_agent.output_key == "youtube_videos_research"

    def test_agent_tools(self):
        """Verify search_and_collect_youtube_data tool is registered with the agent."""
        assert youtube_comments_analyzer_agent.tools is not None
        assert search_and_collect_youtube_data in youtube_comments_analyzer_agent.tools

    def test_orchestrator_sub_agent_order(self):
        """Verify orchestrator contains all sub-agents in the correct sequence."""
        assert len(campaign_orchestrator.sub_agents) >= 2
        assert campaign_orchestrator.sub_agents[0] is landing_page_research_agent
        assert campaign_orchestrator.sub_agents[1] is youtube_comments_analyzer_agent

