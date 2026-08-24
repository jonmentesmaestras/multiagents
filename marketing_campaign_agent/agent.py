import os

from dotenv import load_dotenv
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import google_search

from marketing_campaign_agent.instructions import (
    CAMPAIGN_ORCHESTRATOR_INSTRUCTION,
    MARKET_RESEARCH_INSTRUCTION,
    AD_COPY_WRITER_INSTRUCTION,
    VISUAL_SUGGESTER_INSTRUCTION,
    FORMATTER_INSTRUCTION,
    MESSAGING_STRATEGIST_INSTRUCTION
)

load_dotenv()

MODEL_NAME = os.getenv("GOOGLE_GENAI_MODEL", "gemini-2.0-flash")

# -- Sub agent 1: Market Researcher Agent ---
market_research_agent = LlmAgent(
    name="MarketResearcher",
    model=MODEL_NAME,
    instruction=MARKET_RESEARCH_INSTRUCTION,
    tools=[google_search],
    output_key="market_research_summary",
)

# -- Sub agent 2: Messaging Strategist Agent ---
messaging_strategist_agent = LlmAgent(
    name="MessagingStrategist",
    model=MODEL_NAME,
    instruction=MESSAGING_STRATEGIST_INSTRUCTION,
    output_key="key_messaging",
)

# -- Sub agent 3: Ad Copy Writer Agent ---
ad_copy_writer_agent = LlmAgent(
    name="AdCopyWriter",
    model=MODEL_NAME,
    instruction=AD_COPY_WRITER_INSTRUCTION,
    output_key="ad_copy_variations",
)

# -- Sub agent 4: Visual Suggester Agent ---
visual_suggester_agent = LlmAgent(
    name="VisualSuggester",
    model=MODEL_NAME,
    instruction=VISUAL_SUGGESTER_INSTRUCTION,
    output_key="visual_concepts",
)

# -- Sub agent 5: Formatter Agent ---
formatter_agent = LlmAgent(
    name="Formatter",
    model=MODEL_NAME,
    instruction=FORMATTER_INSTRUCTION,
    output_key="final_campaign_brief",
)

campaign_orchestrator = SequentialAgent(
    name="marketing_campaign_orchestrator",
    description=CAMPAIGN_ORCHESTRATOR_INSTRUCTION,
    sub_agents=[
        market_research_agent,
        messaging_strategist_agent,
        ad_copy_writer_agent,
        visual_suggester_agent,
        formatter_agent,
    ],
)

root_agent = campaign_orchestrator