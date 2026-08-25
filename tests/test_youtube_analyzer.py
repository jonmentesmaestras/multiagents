"""Unit tests for YouTube Comments / Video Analyzer Agent and YouTube search tool."""

import pytest
from google.adk.agents import LlmAgent

from marketing_campaign_agent.agent import (
    campaign_orchestrator,
    landing_page_research_agent,
    youtube_comments_analyzer_agent,
)
from marketing_campaign_agent.tools import parse_view_count, search_youtube_videos


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


class TestYoutubeSearchToolArguments:
    def test_empty_keywords_returns_empty_list(self):
        """Verify calling tool with empty keyword list returns empty list."""
        assert search_youtube_videos([]) == []
        assert search_youtube_videos("") == []
        assert search_youtube_videos(None) == []


class TestYoutubeCommentsAnalyzerAgentConfig:
    def test_agent_type_and_name(self):
        """Verify youtube_comments_analyzer_agent is configured with expected name and type."""
        assert isinstance(youtube_comments_analyzer_agent, LlmAgent)
        assert youtube_comments_analyzer_agent.name == "YoutubeCommentsAnalyzer"

    def test_agent_output_key(self):
        """Verify output_key is configured as youtube_videos_research."""
        assert youtube_comments_analyzer_agent.output_key == "youtube_videos_research"

    def test_agent_tools(self):
        """Verify search_youtube_videos tool is registered with the agent."""
        assert youtube_comments_analyzer_agent.tools is not None
        assert search_youtube_videos in youtube_comments_analyzer_agent.tools

    def test_orchestrator_sub_agent_order(self):
        """Verify orchestrator contains both sub-agents in the correct sequence."""
        assert len(campaign_orchestrator.sub_agents) == 2
        assert campaign_orchestrator.sub_agents[0] is landing_page_research_agent
        assert campaign_orchestrator.sub_agents[1] is youtube_comments_analyzer_agent
