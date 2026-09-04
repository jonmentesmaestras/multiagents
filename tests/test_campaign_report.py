"""Unit and integration tests for Market Research Report & Decision Agent and Comments Evaluator Tool."""

import json
from pathlib import Path
import pytest
from google.adk.agents import LlmAgent

from marketing_campaign_agent.agent import (
    campaign_orchestrator,
    campaign_report_agent,
    landing_page_research_agent,
    market_research_report_agent,
    youtube_comments_analyzer_agent,
    youtube_comments_classifier_agent,
    youtube_comments_collector_agent,
)
from marketing_campaign_agent.tools import evaluate_classified_comments_metrics


class TestCommentsEvaluatorTool:
    def test_scenario_deseos_above_50_accepts_offer(self):
        """Scenario 1: More than 50 comments in deseos -> ACCEPT_OFFER."""
        comments = [{"categoria": "deseo", "Msg": f"Quiero emprender {i}"} for i in range(55)] + [
            {"categoria": "problema", "Msg": f"Problema {i}"} for i in range(10)
        ]
        result = evaluate_classified_comments_metrics(comments)
        assert result["deseos_count"] == 55
        assert result["problemas_count"] == 10
        assert result["total_classified"] == 65
        assert result["deseos_above_50"] is True
        assert result["is_offer_accepted"] is True
        assert result["decision"] == "ACCEPT_OFFER"
        assert "suficiente volumen" in result["conclusion"]
        assert "continuar con el siguiente paso" in result["recommendation"]

    def test_scenario_problemas_above_50_accepts_offer(self):
        """Scenario 2: More than 50 comments in problemas -> ACCEPT_OFFER."""
        comments = [{"categoria": "deseo", "Msg": f"Deseo {i}"} for i in range(15)] + [
            {"categoria": "problema", "Msg": f"Frustración {i}"} for i in range(52)
        ]
        result = evaluate_classified_comments_metrics(comments)
        assert result["deseos_count"] == 15
        assert result["problemas_count"] == 52
        assert result["total_classified"] == 67
        assert result["problemas_above_50"] is True
        assert result["is_offer_accepted"] is True
        assert result["decision"] == "ACCEPT_OFFER"

    def test_scenario_total_up_to_100_accepts_offer(self):
        """Scenario 3: Total sum of deseos and problems reaches 100 -> ACCEPT_OFFER."""
        comments = [{"categoria": "deseo", "Msg": f"Deseo {i}"} for i in range(50)] + [
            {"categoria": "problema", "Msg": f"Problema {i}"} for i in range(50)
        ]
        result = evaluate_classified_comments_metrics(comments)
        assert result["deseos_count"] == 50
        assert result["problemas_count"] == 50
        assert result["total_classified"] == 100
        assert result["total_above_100"] is True
        assert result["is_offer_accepted"] is True
        assert result["decision"] == "ACCEPT_OFFER"

    def test_scenario_insufficient_comments_rejects_offer(self):
        """Scenario 4: Deseos <= 50, Problemas <= 50, and Total < 100 -> DO_NOT_ACCEPT_OFFER."""
        comments = [{"categoria": "deseo", "Msg": f"Deseo {i}"} for i in range(20)] + [
            {"categoria": "problema", "Msg": f"Problema {i}"} for i in range(15)
        ]
        result = evaluate_classified_comments_metrics(comments)
        assert result["deseos_count"] == 20
        assert result["problemas_count"] == 15
        assert result["total_classified"] == 35
        assert result["deseos_above_50"] is False
        assert result["problemas_above_50"] is False
        assert result["total_above_100"] is False
        assert result["is_offer_accepted"] is False
        assert result["decision"] == "DO_NOT_ACCEPT_OFFER"
        assert "NO cuenta con suficiente audiencia" in result["conclusion"]
        assert "NO proceder con ningún clon en español por ahora" in result["recommendation"]

    def test_json_string_input_evaluation(self):
        """Verify tool correctly handles serialized JSON string input."""
        data = [
            {"categoria": "deseo", "Msg": "Quiero comprar"},
            {"categoria": "problema", "Msg": "No funciona"},
        ]
        result = evaluate_classified_comments_metrics(json.dumps(data))
        assert result["deseos_count"] == 1
        assert result["problemas_count"] == 1
        assert result["total_classified"] == 2
        assert result["decision"] == "DO_NOT_ACCEPT_OFFER"

    def test_evaluate_outcome_2_json_fixture_if_exists(self):
        """Test evaluation against real outcome structure or sample fixture."""
        sample_data = [
            {
                "categoria": "deseo",
                "deseo": "Crear un negocio rentable",
                "Msg": "Quiero empezar a vender velas",
                "razon": "Interés en comercialización",
                "video_href": "https://www.youtube.com/watch?v=vid1",
            },
            {
                "categoria": "problema",
                "problema": "Cera agrietada",
                "Msg": "Se me agrieta la cera al secar",
                "razon": "Defecto técnico en la fabricación",
                "video_href": "https://www.youtube.com/watch?v=vid2",
            },
        ]
        result = evaluate_classified_comments_metrics(sample_data)
        assert result["deseos_count"] == 1
        assert result["problemas_count"] == 1
        assert result["total_classified"] == 2
        assert result["decision"] == "DO_NOT_ACCEPT_OFFER"

        # Also test with raw outcome_2.json if valid
        outcome_file = Path(__file__).resolve().parent.parent / "marketing_campaign_agent" / "outcome_2.json"
        if outcome_file.exists() and outcome_file.stat().st_size > 0:
            try:
                with open(outcome_file, "r", encoding="utf-8") as f:
                    comments = json.loads(f.read(), strict=False)
                res = evaluate_classified_comments_metrics(comments)
                assert isinstance(res["deseos_count"], int)
                assert isinstance(res["problemas_count"], int)
            except json.JSONDecodeError:
                pass


class TestMarketResearchReportAgentConfig:
    def test_agent_is_llm_agent(self):
        """Verify report agent is an LlmAgent instance."""
        assert isinstance(market_research_report_agent, LlmAgent)

    def test_agent_name_and_output_key(self):
        """Verify agent name and output key."""
        assert market_research_report_agent.name == "MarketResearchReportAgent"
        assert market_research_report_agent.output_key == "market_research_report"

    def test_agent_alias(self):
        """Verify backward-compatible alias."""
        assert campaign_report_agent is market_research_report_agent

    def test_agent_has_evaluator_tool(self):
        """Verify evaluate_classified_comments_metrics tool is registered with the agent."""
        assert market_research_report_agent.tools is not None
        assert evaluate_classified_comments_metrics in market_research_report_agent.tools

    def test_orchestrator_sub_agents_sequence(self):
        """Verify campaign_orchestrator contains all 5 sub-agents in exact order."""
        assert len(campaign_orchestrator.sub_agents) == 5
        assert campaign_orchestrator.sub_agents[0] is landing_page_research_agent
        assert campaign_orchestrator.sub_agents[1] is youtube_comments_analyzer_agent
        assert campaign_orchestrator.sub_agents[2] is youtube_comments_collector_agent
        assert campaign_orchestrator.sub_agents[3] is youtube_comments_classifier_agent
        assert campaign_orchestrator.sub_agents[4] is market_research_report_agent
