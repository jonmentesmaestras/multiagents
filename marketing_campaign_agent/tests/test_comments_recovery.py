"""Exercise recovery and visible progress through the real ADK event loop."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from marketing_campaign_agent.comments_pipeline import (
    BatchedCommentsClassifierAgent, DeterministicCommentsCollectorAgent, _consolidate_videos,
)
from marketing_campaign_agent.landing_research import GroundedCampaignOrchestrator, STATUS_KEY


RESEARCH = {"deseos": ["Dormir", "Calma", "Aprender"], "problemas": ["Insomnio", "Estrés", "Dudas"]}


def video(vid, ids, status="complete"):
    return {"video_href": f"https://www.youtube.com/watch?v={vid}", "video_keywords": "frecuencias",
            "collection_status": status, "collection_error": "api_failed_fallback_used" if status == "partial" else None,
            "3_months_comments": [{"comment_id": i, "Msg": "Quiero dormir", "Author": "@user",
                                   "video_href": f"https://www.youtube.com/watch?v={vid}"} for i in ids]}


def response(ids, decision="deseo"):
    return MagicMock(text=json.dumps([{"comment_id": i, "decision": decision,
                                     "category_id": "D1" if decision == "deseo" else None} for i in ids]))


class Stage(BaseAgent):
    calls: int = 0
    seed: bool = False

    async def _run_async_impl(self, ctx):
        self.calls += 1
        delta = {STATUS_KEY: {"status": "validated", "invocation_id": ctx.invocation_id},
                 "landing_page_research": json.dumps(RESEARCH), "youtube_videos_research": "[]"} if self.seed else {}
        ctx.session.state.update(delta)
        yield Event(author=self.name, invocation_id=ctx.invocation_id, actions=EventActions(state_delta=delta))


async def run_pipeline(fetch_results, model_results, *, resume=False, initial=None):
    stages = [Stage(name="landing", seed=True), Stage(name="videos"),
              DeterministicCommentsCollectorAgent(name="collector", model="offline"),
              BatchedCommentsClassifierAgent(name="classifier", model="offline"), Stage(name="report")]
    root = GroundedCampaignOrchestrator(name="pipeline", sub_agents=stages)
    service = InMemorySessionService()
    await service.create_session(app_name="test", user_id="u", session_id="s", state=initial or {})
    runner = Runner(agent=root, app_name="test", session_service=service)
    client = MagicMock()
    client.models.generate_content.side_effect = model_results
    with patch("marketing_campaign_agent.comments_pipeline.extract_comments_from_videos",
               side_effect=deepcopy(fetch_results)) as fetch, patch("google.genai.Client", return_value=client):
        events = [e async for e in runner.run_async(user_id="u", session_id="s", new_message=types.Content(
            role="user", parts=[types.Part.from_text(text="reanuda" if resume else "https://example.com")]))]
    state = (await service.get_session(app_name="test", user_id="u", session_id="s")).state
    messages = [p.text for e in events if e.content for p in e.content.parts or [] if p.text]
    return state, messages, stages, fetch, client


def test_partial_video_is_retried_without_collecting_successful_videos_again():
    good, bad, repaired = video("a", ["a"]), video("b", [], "partial"), video("b", ["b"])
    state, messages, stages, fetch, client = asyncio.run(run_pipeline([[good, bad], [repaired]], [response(["a", "b"])]))
    assert fetch.call_count == 2
    assert [v["video_href"] for v in fetch.call_args_list[1].args[0]] == [bad["video_href"]]
    assert state["youtube_comments_collection_status"]["status"] == "complete"
    assert state["market_research_metrics"]["coverage"]["status"] == "verified"
    assert stages[-1].calls == 1
    assert any("Recuperando" in m for m in messages)
    assert any("Clasificando lote 1/1" in m for m in messages)
    client.close.assert_called_once()


def test_persistent_partial_video_continues_classification_and_emits_incomplete_report():
    good, bad = video("a", ["a"]), video("b", [], "partial")
    state, messages, stages, fetch, client = asyncio.run(run_pipeline(
        [[good, bad], [bad], [bad]], [response(["a"])]))
    assert fetch.call_count == 3
    assert client.models.generate_content.call_count == 1
    assert state["youtube_comments_classification_status"]["result_count"] == 1
    assert state["market_research_metrics"]["decision"] == "INCOMPLETE_ANALYSIS"
    assert stages[-1].calls == 0
    assert "INCOMPLETE_ANALYSIS" in messages[-1]
    assert any("Continúo clasificando" in m for m in messages)


def test_resume_uses_saved_collection_and_skips_landing_and_video_search():
    good, bad, repaired = video("a", ["a"]), video("b", [], "partial"), video("b", ["b"])
    state, messages, stages, fetch, _ = asyncio.run(run_pipeline(
        [[repaired]], [response(["a", "b"])], resume=True, initial={
            STATUS_KEY: {"status": "validated", "invocation_id": "previous"},
            "landing_page_research": json.dumps(RESEARCH), "youtube_videos_research": "[]",
            "youtube_comments_collected": json.dumps([good, bad]),
        }))
    assert stages[0].calls == stages[1].calls == 0
    assert fetch.call_count == 1
    assert fetch.call_args.args[0][0]["video_href"] == bad["video_href"]
    assert state["youtube_comments_classification_status"]["result_count"] == 2
    assert "Reanudando" in messages[0]


def test_failed_batch_does_not_hide_progress_or_discard_other_batches():
    ids = [str(i) for i in range(26)]
    state, messages, _, _, client = asyncio.run(run_pipeline(
        [[video("a", ids)]], [MagicMock(text="[]"), MagicMock(text="[]"), MagicMock(text="[]"), response(["25"])]))
    rows = json.loads(state["youtube_comments_classified"])
    assert len(rows) == len({r["comment_id"] for r in rows}) == 26
    assert state["youtube_comments_checkpoint"]["result_count"] == 26
    assert state["youtube_comments_classification_status"]["review_count"] == 25
    assert client.models.generate_content.call_count == 4
    assert any("lote 2/2" in m for m in messages)
    assert state["market_research_metrics"]["decision"] == "INCOMPLETE_ANALYSIS"


def test_resume_retries_review_items_and_reuses_validated_decisions():
    ids = [str(i) for i in range(26)]
    initial, _, _, _, _ = asyncio.run(run_pipeline(
        [[video("a", ids)]], [MagicMock(text="[]"), MagicMock(text="[]"), MagicMock(text="[]"), response(["25"])]))
    state, _, stages, fetch, client = asyncio.run(run_pipeline(
        [], [response(ids[:25])], resume=True, initial=dict(initial)))
    fetch.assert_not_called()
    assert client.models.generate_content.call_count == 1
    assert state["youtube_comments_classification_status"]["review_count"] == 0
    assert len(json.loads(state["youtube_comments_classified"])) == 26
    assert stages[-1].calls == 1


def test_consolidation_merges_duplicate_videos_and_threads_without_losing_text():
    first = video("a", ["a"])
    second = video("a", ["a", "b"])
    result, stats = _consolidate_videos([first, second])
    assert len(result) == 1
    assert [x["comment_id"] for x in result[0]["3_months_comments"]] == ["a", "b"]
    assert stats["duplicate_videos"] == 1
    assert stats["duplicate_comments"] == 1
