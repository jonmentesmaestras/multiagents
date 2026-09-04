"""Exercise recovery and visible progress through the real ADK event loop."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

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


async def run_pipeline(fetch_results, model_results, *, resume=False, initial=None, message=None):
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
               side_effect=deepcopy(fetch_results)) as fetch, patch("google.genai.Client", return_value=client), \
            patch('marketing_campaign_agent.comments_pipeline.asyncio.sleep', new_callable=AsyncMock), \
            patch('marketing_campaign_agent.diagnostics.export_human_review.export', return_value={'html': 'review.html', 'json': 'review.json'}):
        events = [e async for e in runner.run_async(user_id="u", session_id="s", new_message=types.Content(
            role="user", parts=[types.Part.from_text(text=message or ("reanuda" if resume else "https://example.com"))]))]
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
        [[good, bad], [bad], [bad], [bad]], [response(["a"])]))
    assert fetch.call_count == 4
    assert client.models.generate_content.call_count == 1
    assert state["youtube_comments_classification_status"]["result_count"] == 1
    assert state["market_research_metrics"]["decision"] == "INCOMPLETE_ANALYSIS"
    assert stages[-1].calls == 0
    assert any("INCOMPLETE_ANALYSIS" in x for x in messages)
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
        [[video("a", ids)]], lambda **kw: response(['25']) if '"comment_id": "25"' in kw['contents'] else MagicMock(text='[]')))
    rows = json.loads(state["youtube_comments_classified"])
    assert len(rows) == len({r["comment_id"] for r in rows}) == 26
    assert state["youtube_comments_checkpoint"]["result_count"] == 26
    assert state["youtube_comments_classification_status"]["review_count"] == 25
    assert client.models.generate_content.call_count > 4
    assert state['youtube_comments_recovery']['round'] == 3
    assert len(state['youtube_comments_recovery']['pending_ids']) == 25
    assert any("lote 2/2" in m for m in messages)
    assert state["market_research_metrics"]["decision"] == "INCOMPLETE_ANALYSIS"


def test_recovery_shrinks_failed_batch_and_keeps_successful_decisions():
    ids = [str(i) for i in range(26)]
    calls = []
    def model(**kw):
        batch = json.loads(kw['contents'].split('COMENTARIOS=')[1])
        calls.append([x['comment_id'] for x in batch])
        return MagicMock(text='[]') if len(batch) > 10 else response([x['comment_id'] for x in batch])
    state, _, stages, fetch, client = asyncio.run(run_pipeline([[video('a', ids)]], model))
    assert sum('25' in batch for batch in calls) == 1
    assert state['youtube_comments_recovery']['round'] == 1
    assert state["youtube_comments_classification_status"]["review_count"] == 0
    assert len(json.loads(state["youtube_comments_classified"])) == 26
    assert stages[-1].calls == 1


def test_semantic_ambiguity_is_not_retried():
    state, _, _, _, client = asyncio.run(run_pipeline([[video('a', ['a'])]], [response(['a'], 'requiere_revision')]))
    assert client.models.generate_content.call_count == 1
    row = json.loads(state['youtube_comments_classified'])[0]
    assert row['failure_kind'] == 'semantic_ambiguity'
    assert state['youtube_comments_classification_status']['technical_error_count'] == 0


def test_permanent_error_stops_recovery():
    class Forbidden(Exception):
        code = 403
    state, _, _, _, client = asyncio.run(run_pipeline([[video('a', ['a'])]], Forbidden('blocked')))
    assert client.models.generate_content.call_count == 1
    assert state['youtube_comments_recovery']['stop_reason'] == 'permanent_error'


def test_threshold_during_recovery_stops_further_calls():
    def model(**kw):
        batch = json.loads(kw['contents'].split('COMENTARIOS=')[1])
        return MagicMock(text='[]') if len(batch) > 10 else response([x['comment_id'] for x in batch])
    with patch('marketing_campaign_agent.comments_pipeline.CLASSIFICATION_TARGET', 10):
        state, _, _, _, client = asyncio.run(run_pipeline([[video('a', [str(x) for x in range(25)])]], model))
    assert client.models.generate_content.call_count == 4
    assert state['youtube_comments_classification_status']['target_reached']
    assert len(json.loads(state['youtube_comments_classified'])) == 25


def test_session_lease_excludes_concurrent_execution():
    from marketing_campaign_agent.recovery_runtime import SessionLease
    a, b = SessionLease('test-exclusive-session'), SessionLease('test-exclusive-session')
    assert a.acquire()
    try:
        assert not b.acquire()
    finally:
        a.release()
    assert b.acquire()
    b.release()


def test_only_interrupted_comment_runs_are_restarted():
    from marketing_campaign_agent.recovery_server import eligible_for_restart
    for status in ['cancelled', 'failed', 'finished']:
        assert not eligible_for_restart({'pipeline_run': {'status': status, 'stage': 3},
                                         'youtube_comments_collected': '[{}]'})
    assert eligible_for_restart({'pipeline_run': {'status': 'active', 'stage': 3},
                                 'youtube_comments_collected': '[{}]'})
    assert not eligible_for_restart({'pipeline_run': {'status': 'active', 'stage': 1}})


def test_automatic_resume_reuses_checkpoint_without_user_word():
    from marketing_campaign_agent.recovery_runtime import AUTO_RESUME
    initial, _, _, _, _ = asyncio.run(run_pipeline([[video('a', ['a'])]], [response(['a'], 'no_aplica')]))
    initial['pipeline_run'] = {'status': 'active', 'stage': 3, 'restart_attempts': 0}
    state, _, stages, fetch, client = asyncio.run(run_pipeline([], [], initial=initial, message=AUTO_RESUME))
    fetch.assert_not_called()
    client.models.generate_content.assert_not_called()
    assert stages[0].calls == stages[1].calls == 0
    assert state['pipeline_run']['restart_attempts'] == 1
    assert state['pipeline_run']['status'] == 'finished'
    assert len(json.loads(state['youtube_comments_classified'])) == 1


def test_startup_worker_dispatches_saved_session_via_adk_endpoint():
    import httpx
    from marketing_campaign_agent.recovery_server import recover_on_startup
    from marketing_campaign_agent.recovery_runtime import AUTO_RESUME
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[] if request.method == 'GET' else {})
    real_client = httpx.AsyncClient
    def client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)
    with patch('marketing_campaign_agent.recovery_server.interrupted_sessions', return_value=[('test', 'u', 's')]), \
            patch('marketing_campaign_agent.recovery_server.httpx.AsyncClient', side_effect=client):
        asyncio.run(recover_on_startup('http://127.0.0.1:8000'))
    assert requests[1].url.path == '/run_sse'
    assert json.loads(requests[1].content)['new_message']['parts'][0]['text'] == AUTO_RESUME


def test_user_cancellation_is_persisted_and_releases_lease():
    async def scenario():
        started = asyncio.Event()
        class WaitingStage(BaseAgent):
            async def _run_async_impl(self, ctx):
                started.set()
                await asyncio.Event().wait()
                yield
        root = GroundedCampaignOrchestrator(name='cancel_root', sub_agents=[WaitingStage(name='waiting')])
        service = InMemorySessionService()
        await service.create_session(app_name='test', user_id='u', session_id='cancel')
        runner = Runner(agent=root, app_name='test', session_service=service)
        async def consume():
            async for _ in runner.run_async(user_id='u', session_id='cancel', new_message=types.Content(
                    role='user', parts=[types.Part.from_text(text='https://example.com')])):
                pass
        task = asyncio.create_task(consume())
        await started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        state = (await service.get_session(app_name='test', user_id='u', session_id='cancel')).state
        assert state['pipeline_run']['status'] == 'cancelled'
        from marketing_campaign_agent.recovery_runtime import SessionLease
        lease = SessionLease('test:u:cancel')
        assert lease.acquire()
        lease.release()
    asyncio.run(scenario())


def test_consolidation_merges_duplicate_videos_and_threads_without_losing_text():
    first = video("a", ["a"])
    second = video("a", ["a", "b"])
    result, stats = _consolidate_videos([first, second])
    assert len(result) == 1
    assert [x["comment_id"] for x in result[0]["3_months_comments"]] == ["a", "b"]
    assert stats["duplicate_videos"] == 1
    assert stats["duplicate_comments"] == 1
