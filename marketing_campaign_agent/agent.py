import os

from dotenv import find_dotenv, load_dotenv
from google.adk.agents import LlmAgent, SequentialAgent

from marketing_campaign_agent.instructions import (
    CAMPAIGN_ORCHESTRATOR_INSTRUCTION,
    LANDING_PAGE_COPYWRITER_INSTRUCTION,
    YOUTUBE_COMMENTS_ANALYZER_INSTRUCTION,
)
from marketing_campaign_agent.tools import (
    scrape_landing_page,
    search_youtube_videos,
)

load_dotenv(find_dotenv())

MODEL_NAME = os.getenv("GOOGLE_GENAI_MODEL", "gemini-3.6-flash")

# -- Sub agent 1: Market Researcher Agent ---
landing_page_research_agent = LlmAgent(
    name="LandingPageResearcher",
    model=MODEL_NAME,
    instruction=LANDING_PAGE_COPYWRITER_INSTRUCTION,
    output_key="landing_page_research",
    tools=[scrape_landing_page],
)

# -- Sub agent 2: Youtube Comments Analyzer Agent ---
youtube_comments_analyzer_agent = LlmAgent(
    name="YoutubeCommentsAnalyzer",
    model=MODEL_NAME,
    instruction=YOUTUBE_COMMENTS_ANALYZER_INSTRUCTION,
    output_key="youtube_videos_research",
    tools=[search_youtube_videos],
)

campaign_orchestrator = SequentialAgent(
    name="marketing_campaign_orchestrator",
    description=CAMPAIGN_ORCHESTRATOR_INSTRUCTION,
    sub_agents=[
        landing_page_research_agent,
        youtube_comments_analyzer_agent,
    ],
)

root_agent = campaign_orchestrator