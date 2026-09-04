"""Unit and integration tests for YouTube Comments Classifier Agent."""

import json
import pytest
from google.adk.agents import LlmAgent

from marketing_campaign_agent.agent import (
    campaign_orchestrator,
    landing_page_research_agent,
    youtube_comment_classifier_agent,
    youtube_comments_analyzer_agent,
    youtube_comments_classifier_agent,
    youtube_comments_collector_agent,
)
from marketing_campaign_agent.instructions import (
    YOUTUBE_COMMENTS_CLASSIFIER_INSTRUCTION,
)


class TestYoutubeCommentsClassifierAgentConfig:
    def test_agent_is_llm_agent(self):
        """Verify classifier agent is configured as an LlmAgent."""
        assert isinstance(youtube_comments_classifier_agent, LlmAgent)

    def test_agent_name_and_output_key(self):
        """Verify classifier agent name and session state output key."""
        assert youtube_comments_classifier_agent.name == "YoutubeCommentsClassifier"
        assert youtube_comments_classifier_agent.output_key == "youtube_comments_classified"

    def test_agent_alias_compatibility(self):
        """Verify alias points to the same classifier agent instance."""
        assert youtube_comment_classifier_agent is youtube_comments_classifier_agent

    def test_instruction_content(self):
        """Verify instruction contains core prompt elements: deseos, problemas, Msg, razon, and schema."""
        instruction = youtube_comments_classifier_agent.instruction
        assert instruction is not None
        assert "YouTube Comments Classifier Agent" in instruction
        assert "landing_page_research" in instruction
        assert "youtube_comments_collected" in instruction
        assert "deseos" in instruction
        assert "problemas" in instruction
        assert "categoria" in instruction
        assert "razon" in instruction
        assert "video_href" in instruction

    def test_orchestrator_sub_agents_position(self):
        """Verify classifier agent is registered as the 4th agent in sequential orchestrator."""
        assert len(campaign_orchestrator.sub_agents) >= 4
        assert campaign_orchestrator.sub_agents[0] is landing_page_research_agent
        assert campaign_orchestrator.sub_agents[1] is youtube_comments_analyzer_agent
        assert campaign_orchestrator.sub_agents[2] is youtube_comments_collector_agent
        assert campaign_orchestrator.sub_agents[3] is youtube_comments_classifier_agent


class TestClassificationSchemaValidation:
    def test_valid_deseo_item_schema(self):
        """Verify desire classification object conforms to required schema."""
        deseo_item = {
            "categoria": "deseo",
            "deseo": "Crear un negocio rentable y sostenible desde casa vendiendo velas aromáticas",
            "Msg": "en cuanto puedo vender unas velas de vainilla para diciembre",
            "razon": "Si la persona pregunta el precio por el cual lo quisiera vender, es porque está pensando en un negocio",
            "video_href": "https://www.youtube.com/watch?v=tPcRVA3CwdA",
        }
        assert deseo_item["categoria"] == "deseo"
        assert "deseo" in deseo_item
        assert "Msg" in deseo_item
        assert "razon" in deseo_item
        assert "video_href" in deseo_item

    def test_valid_problema_item_schema(self):
        """Verify problem classification object conforms to required schema."""
        problema_item = {
            "categoria": "problema",
            "problema": "Frustración porque las velas no desprenden suficiente aroma en caliente (hot throw)",
            "Msg": "la vela termina por consumirse y no desprende suficiente aroma a vainilla",
            "razon": "Problema del hot throw y falta de retención del aroma",
            "video_href": "https://www.youtube.com/watch?v=pEhEKA8OXB0",
        }
        assert problema_item["categoria"] == "problema"
        assert "problema" in problema_item
        assert "Msg" in problema_item
        assert "razon" in problema_item
        assert "video_href" in problema_item

    def test_json_serialization_of_classified_output(self):
        """Verify structured classification array can be cleanly parsed as JSON."""
        classified_data = [
            {
                "categoria": "deseo",
                "deseo": "Aprender técnicas de negocio",
                "Msg": "¿Cómo puedo empezar mi emprendimiento?",
                "razon": "Interés explícito en emprender",
                "video_href": "https://www.youtube.com/watch?v=vid1",
            },
            {
                "categoria": "problema",
                "problema": "Cera agrietada o túneles",
                "Msg": "Se me separa la cera del vaso de vidrio",
                "razon": "Defecto técnico en la fabricación",
                "video_href": "https://www.youtube.com/watch?v=vid2",
            },
        ]
        json_str = json.dumps(classified_data, ensure_ascii=False)
        parsed = json.loads(json_str)
        assert len(parsed) == 2
        assert parsed[0]["categoria"] == "deseo"
        assert parsed[1]["categoria"] == "problema"
