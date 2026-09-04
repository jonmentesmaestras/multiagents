"""Unit and integration tests for marketing_campaign_agent, Playwright tool, and ADK Web."""

import asyncio

import pytest
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.cli.utils.agent_loader import AgentLoader

from marketing_campaign_agent.agent import (
    campaign_orchestrator,
    campaign_report_agent,
    landing_page_research_agent,
    market_research_report_agent,
    root_agent,
    youtube_comment_classifier_agent,
    youtube_comment_extractor_agent,
    youtube_comments_analyzer_agent,
    youtube_comments_classifier_agent,
    youtube_comments_collector_agent,
)
from marketing_campaign_agent.tools import scrape_landing_page
from marketing_campaign_agent.landing_research import GroundedLandingPageAgent


class TestAgentConfiguration:
    def test_root_agent_is_sequential_agent(self):
        """Verify root_agent is configured as the sequential campaign orchestrator."""
        assert isinstance(root_agent, SequentialAgent)
        assert root_agent.name == "marketing_campaign_orchestrator"
        assert root_agent is campaign_orchestrator

    def test_orchestrator_sub_agents(self):
        """Verify orchestrator contains all five sub-agents in order."""
        assert len(campaign_orchestrator.sub_agents) == 5
        assert campaign_orchestrator.sub_agents[0] is landing_page_research_agent
        assert campaign_orchestrator.sub_agents[1] is youtube_comments_analyzer_agent
        assert campaign_orchestrator.sub_agents[2] is youtube_comments_collector_agent
        assert campaign_orchestrator.sub_agents[3] is youtube_comments_classifier_agent
        assert campaign_orchestrator.sub_agents[4] is market_research_report_agent
        assert youtube_comments_collector_agent.name == "YoutubeCommentsCollector"
        assert youtube_comment_extractor_agent is youtube_comments_collector_agent
        assert youtube_comments_classifier_agent.name == "YoutubeCommentsClassifier"
        assert youtube_comment_classifier_agent is youtube_comments_classifier_agent
        assert market_research_report_agent.name == "MarketResearchReportAgent"
        assert campaign_report_agent is market_research_report_agent



    def test_landing_page_research_agent_config(self):
        """Verify landing page research agent settings, tools, and output key."""
        assert isinstance(landing_page_research_agent, LlmAgent)
        assert landing_page_research_agent.name == "LandingPageResearcher"
        assert landing_page_research_agent.output_key == "landing_page_research"
        assert landing_page_research_agent.instruction is not None
        assert "Landing Page Copywriter Agent" in landing_page_research_agent.instruction

    def test_landing_page_research_agent_requires_extraction_before_model(self):
        """Extraction runs in Python before model inference, never as an optional tool."""
        assert isinstance(landing_page_research_agent, GroundedLandingPageAgent)
        assert landing_page_research_agent.tools == []
        assert asyncio.iscoroutinefunction(scrape_landing_page)


class TestPlaywrightScraperTool:
    def test_invalid_url_handling(self):
        """Verify tool gracefully handles invalid URLs without throwing unhandled exceptions."""
        result = asyncio.run(scrape_landing_page("http://"))
        assert "error" in result

    def test_scrape_landing_page_structure(self):
        """Verify scraper extracts expected schema from a live or mock URL."""
        result = asyncio.run(scrape_landing_page("https://example.com"))
        assert "url" in result
        if "error" in result:
            pytest.skip("Chromium is unavailable in this test environment")
        assert "title" in result
        assert "suggested_page_type" in result
        assert result["suggested_page_type"] in ["VSL", "TSL"]
        assert "video_detected" in result
        assert isinstance(result["video_detected"], bool)
        assert "headings" in result
        assert isinstance(result["headings"], list)
        assert "call_to_action_buttons" in result
        assert isinstance(result["call_to_action_buttons"], list)
        assert "main_content" in result
        assert len(result["main_content"]) > 0


class TestAdkDiscoveryAndWebCompat:
    def test_agent_loader_discovery(self):
        """Verify Google ADK AgentLoader can discover and load marketing_campaign_agent."""
        loader = AgentLoader(agents_dir=".")
        loaded = loader.load_agent("marketing_campaign_agent")
        assert loaded is not None
        assert getattr(loaded, "name", "") == "marketing_campaign_orchestrator"

    def test_adk_web_fastapi_app_initialization(self):
        """Verify ADK Web FastAPI application initializes correctly with all routes."""
        app = get_fast_api_app(agents_dir=".", web=True)
        assert app is not None
        route_paths = [route.path for route in app.routes]
        assert len(route_paths) > 0
        assert "/" in route_paths
