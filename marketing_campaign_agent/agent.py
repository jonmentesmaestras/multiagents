import os

from dotenv import find_dotenv, load_dotenv
from google.adk.agents import LlmAgent, SequentialAgent
from google.genai import types

from marketing_campaign_agent.landing_research import (
    GroundedCampaignOrchestrator,
    GroundedLandingPageAgent,
    current_source_only,
)

from marketing_campaign_agent.instructions import (
    CAMPAIGN_ORCHESTRATOR_INSTRUCTION,
    CAMPAIGN_REPORT_INSTRUCTION,
    LANDING_PAGE_COPYWRITER_INSTRUCTION,
    MARKET_RESEARCH_REPORT_INSTRUCTION,
    YOUTUBE_COMMENTS_ANALYZER_INSTRUCTION,
    YOUTUBE_COMMENTS_CLASSIFIER_INSTRUCTION,
    YOUTUBE_COMMENTS_COLLECTOR_INSTRUCTION,
    YOUTUBE_COMMENT_EXTRACTOR_INSTRUCTION,
)
from marketing_campaign_agent.comments_pipeline import (
    BatchedVideoAnalyzerAgent,
    BatchedCommentsClassifierAgent,
    DETERMINISTIC_GENERATION_SEED,
    DeterministicCommentsCollectorAgent,
    report_metrics_context,
)
from marketing_campaign_agent.tools import (
    collect_youtube_comments,
    evaluate_classified_comments_metrics,
    validate_comments_integrity,
    extract_comments_from_videos,
    scrape_landing_page,
    search_and_collect_youtube_data,
    search_youtube_videos,
)

load_dotenv(find_dotenv())

MODEL_NAME = os.getenv("GOOGLE_GENAI_MODEL", "gemini-3.6-flash")

# -- Sub agent 1: Market Researcher Agent ---
landing_page_research_agent = GroundedLandingPageAgent(
    name="LandingPageResearcher",
    model=MODEL_NAME,
    instruction=LANDING_PAGE_COPYWRITER_INSTRUCTION,
    output_key="landing_page_research",
    # Extraction is mandatory in Python, before the model can generate anything.
    tools=[],
    include_contents="none",
    before_model_callback=current_source_only,
    generate_content_config=types.GenerateContentConfig(
        response_mime_type="application/json", temperature=0,
        seed=DETERMINISTIC_GENERATION_SEED, candidate_count=1),
)

# -- Sub agent 2: Youtube Comments Analyzer Agent ---
youtube_comments_analyzer_agent = BatchedVideoAnalyzerAgent(
    name="YoutubeCommentsAnalyzer",
    model=MODEL_NAME,
    instruction=YOUTUBE_COMMENTS_ANALYZER_INSTRUCTION,
    output_key="youtube_videos_research",
    tools=[],
)

# -- Sub agent 3: Youtube Comments Collector Agent ---
youtube_comments_collector_agent = DeterministicCommentsCollectorAgent(
    name="YoutubeCommentsCollector",
    model=MODEL_NAME,
    instruction=YOUTUBE_COMMENTS_COLLECTOR_INSTRUCTION,
    output_key="youtube_comments_collected",
    tools=[extract_comments_from_videos],
    generate_content_config=types.GenerateContentConfig(
        response_mime_type="application/json", temperature=0,
        seed=DETERMINISTIC_GENERATION_SEED, candidate_count=1),
)

# Alias for backward compatibility
youtube_comment_extractor_agent = youtube_comments_collector_agent

# -- Sub agent 4: Youtube Comments Classifier Agent ---
youtube_comments_classifier_agent = BatchedCommentsClassifierAgent(
    name="YoutubeCommentsClassifier",
    model=MODEL_NAME,
    instruction=YOUTUBE_COMMENTS_CLASSIFIER_INSTRUCTION,
    output_key="youtube_comments_classified",
    generate_content_config=types.GenerateContentConfig(
        response_mime_type="application/json", temperature=0,
        seed=DETERMINISTIC_GENERATION_SEED, candidate_count=1),
)

# Alias for backward compatibility
youtube_comment_classifier_agent = youtube_comments_classifier_agent

# -- Sub agent 5: Market Research Report & Decision Agent ---
market_research_report_agent = LlmAgent(
    name="MarketResearchReportAgent",
    model=MODEL_NAME,
    instruction=MARKET_RESEARCH_REPORT_INSTRUCTION,
    output_key="market_research_report",
    tools=[evaluate_classified_comments_metrics, validate_comments_integrity],
    include_contents="none",
    before_model_callback=report_metrics_context,
    generate_content_config=types.GenerateContentConfig(
        temperature=0, seed=DETERMINISTIC_GENERATION_SEED, candidate_count=1),
)

# Alias for backward compatibility
campaign_report_agent = market_research_report_agent


campaign_orchestrator = GroundedCampaignOrchestrator(
    name="marketing_campaign_orchestrator",
    description=CAMPAIGN_ORCHESTRATOR_INSTRUCTION,
    sub_agents=[
        landing_page_research_agent,
        youtube_comments_analyzer_agent,
        youtube_comments_collector_agent,
        youtube_comments_classifier_agent,
        market_research_report_agent,
    ],
)

root_agent = campaign_orchestrator
