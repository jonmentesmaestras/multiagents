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
    _market_signal_reached_counts,
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
                                     "category_id": ("D1" if decision == "deseo" else
                                                     "P1" if decision == "problema" else None)}
                                    for i in ids]))


class Stage(BaseAgent):
    calls: int = 0
    seed: bool = False
    video_candidates: list[dict] | None = None
    search_status: dict | None = None

    async def _run_async_impl(self, ctx):
        self.calls += 1
        delta = {STATUS_KEY: {"status": "validated", "invocation_id": ctx.invocation_id},
                 "landing_page_research": json.dumps(RESEARCH), "youtube_videos_research": "[]"} if self.seed else {}
        if self.video_candidates is not None:
            delta["youtube_videos_research"] = json.dumps(self.video_candidates)
        if self.search_status is not None:
            delta["youtube_search_status"] = self.search_status
        ctx.session.state.update(delta)
        yield Event(author=self.name, invocation_id=ctx.invocation_id, actions=EventActions(state_delta=delta))


async def run_pipeline(fetch_results, model_results, *, resume=False, initial=None, message=None):
    stages = [Stage(name="landing", seed=True), Stage(name="videos", video_candidates=[{
                  "video_href": "https://www.youtube.com/watch?v=accepted",
                  "video_title": "Frecuencias para dormir",
                  "video_keywords": "frecuencias para dormir",
                  "relevance_decision": "accepted",
                  "detected_language": "es",
                  "relevance_reason": "Coincide con la landing",
              }]),
              DeterministicCommentsCollectorAgent(name="collector", model="offline"),
              BatchedCommentsClassifierAgent(name="classifier", model="offline"), Stage(name="report")]
    root = GroundedCampaignOrchestrator(name="pipeline", sub_agents=stages)
    service = InMemorySessionService()
    await service.create_session(app_name="test", user_id="u", session_id="s", state=initial or {})
    runner = Runner(agent=root, app_name="test", session_service=service)
    client = MagicMock()
    generate_content = AsyncMock(side_effect=model_results)
    client.aio.models.generate_content = generate_content
    client.aio.aclose = AsyncMock()
    # Keep the existing assertions readable while the classifier uses the
    # cancelable async transport in production.
    client.models.generate_content = generate_content
    with patch("marketing_campaign_agent.comments_pipeline.extract_comments_from_videos",
               side_effect=deepcopy(fetch_results)) as fetch, patch("google.genai.Client", return_value=client), \
            patch('marketing_campaign_agent.comments_pipeline.asyncio.sleep', new_callable=AsyncMock), \
            patch('marketing_campaign_agent.diagnostics.export_human_review.export', return_value={'html': 'review.html', 'json': 'review.json'}):
        events = [e async for e in runner.run_async(user_id="u", session_id="s", new_message=types.Content(
            role="user", parts=[types.Part.from_text(text=message or ("reanuda" if resume else "https://example.com"))]))]
    state = (await service.get_session(app_name="test", user_id="u", session_id="s")).state
    messages = [p.text for e in events if e.content for p in e.content.parts or [] if p.text]
    return state, messages, stages, fetch, client


def test_collector_never_extracts_rejected_video():
    async def scenario():
        collector = DeterministicCommentsCollectorAgent(name="collector", model="offline")
        service = InMemorySessionService()
        candidates = [
            {"video_href": "https://www.youtube.com/watch?v=nails", "relevance_decision": "accepted",
             "detected_language": "es"},
            {"video_href": "https://www.youtube.com/watch?v=cancer", "relevance_decision": "rejected",
             "detected_language": "es"},
            {"video_href": "https://www.youtube.com/watch?v=nails-pt", "relevance_decision": "accepted",
             "detected_language": "pt-BR"},
        ]
        await service.create_session(app_name="test", user_id="u", session_id="s", state={
            "youtube_videos_research": json.dumps(candidates),
        })
        runner = Runner(agent=collector, app_name="test", session_service=service)
        with patch("marketing_campaign_agent.comments_pipeline.extract_comments_from_videos",
                   return_value=[video("nails", ["c1"])]) as extract:
            async for _ in runner.run_async(user_id="u", session_id="s", new_message=types.Content(
                    role="user", parts=[types.Part.from_text(text="run")])):
                pass
        sent = extract.call_args.args[0]
        assert [item["video_href"] for item in sent] == [candidates[0]["video_href"]]
        session = await service.get_session(app_name="test", user_id="u", session_id="s")
        status = session.state["youtube_comments_collection_status"]
        assert status["accepted_videos"] == 1
        assert status["rejected_videos"] == 2
    asyncio.run(scenario())


def test_complete_search_without_accepted_videos_finishes_cleanly():
    async def scenario():
        rejected = [{
            "video_id": "unrelated", "video_href": "https://www.youtube.com/watch?v=unrelated",
            "relevance_decision": "rejected", "detected_language": "es",
        }]
        stages = [
            Stage(name="landing", seed=True),
            Stage(name="YoutubeCommentsAnalyzer", video_candidates=rejected, search_status={
                "status": "complete", "query_count": 12, "completed_queries": 12,
                "query_error_count": 0, "candidate_count": 1, "candidates_decided": 1,
                "candidates_review": 0, "accepted": 0, "rejected": 1,
            }),
            Stage(name="collector"), Stage(name="classifier"), Stage(name="report"),
        ]
        root = GroundedCampaignOrchestrator(name="pipeline", sub_agents=stages)
        service = InMemorySessionService()
        await service.create_session(app_name="test", user_id="u", session_id="s", state={})
        runner = Runner(agent=root, app_name="test", session_service=service)
        events = [event async for event in runner.run_async(
            user_id="u", session_id="s", new_message=types.Content(
                role="user", parts=[types.Part.from_text(text="https://example.com")]))]
        state = (await service.get_session(app_name="test", user_id="u", session_id="s")).state
        messages = [part.text for event in events if event.content
                    for part in event.content.parts or [] if part.text]
        assert [stage.calls for stage in stages] == [1, 1, 0, 0, 0]
        assert state["market_research_metrics"]["decision"] == "DO_NOT_ACCEPT_OFFER"
        assert state["youtube_comments_collection_status"]["status"] == "complete"
        assert state["youtube_comments_classification_status"]["status"] == "complete"
        assert state["youtube_comments_collected"] == state["youtube_comments_classified"] == "[]"
        assert "DO_NOT_ACCEPT_OFFER" in state["market_research_report"]
        assert not any("Extracción detenida" in message or "No se pudo completar" in message
                       for message in messages)

    asyncio.run(scenario())


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


def test_incomplete_collection_resume_fetches_only_missing_video():
    first = video("a", ["a"])
    candidates = [{
        "video_href": f"https://www.youtube.com/watch?v={vid}",
        "relevance_decision": "accepted", "detected_language": "es",
    } for vid in ("a", "b")]
    state, _, stages, fetch, _ = asyncio.run(run_pipeline(
        [[video("b", ["b"])]], [response(["a", "b"])], resume=True, initial={
            STATUS_KEY: {"status": "validated", "invocation_id": "previous"},
            "landing_page_research": json.dumps(RESEARCH),
            "youtube_videos_research": json.dumps(candidates),
            "youtube_comments_collected": json.dumps([first]),
            "youtube_comments_collection_status": {"status": "collecting"},
        }))
    assert stages[0].calls == stages[1].calls == 0
    assert fetch.call_count == 1
    assert [item["video_href"] for item in fetch.call_args.args[0]] == [candidates[1]["video_href"]]
    assert state["youtube_comments_collection_status"]["status"] == "complete"
    assert state["youtube_comments_classification_status"]["result_count"] == 2


def test_collection_emits_and_persists_progress_per_video():
    async def scenario():
        collector = DeterministicCommentsCollectorAgent(name="collector", model="offline")
        service = InMemorySessionService()
        candidates = [{
            "video_href": f"https://www.youtube.com/watch?v={vid}",
            "relevance_decision": "accepted", "detected_language": "es",
        } for vid in ("a", "b")]
        await service.create_session(app_name="test", user_id="u", session_id="progress", state={
            "youtube_videos_research": json.dumps(candidates),
        })
        runner = Runner(agent=collector, app_name="test", session_service=service)

        def extract(_videos, **kwargs):
            rows = [video("a", ["a"]), video("b", ["b"])]
            for index, row in enumerate(rows, 1):
                kwargs["on_video_collected"](row, index, len(rows))
            return rows

        with patch("marketing_campaign_agent.comments_pipeline.extract_comments_from_videos", side_effect=extract):
            events = [event async for event in runner.run_async(
                user_id="u", session_id="progress", new_message=types.Content(
                    role="user", parts=[types.Part.from_text(text="run")]))]
        messages = [part.text for event in events if event.content
                    for part in event.content.parts or [] if part.text]
        session = await service.get_session(app_name="test", user_id="u", session_id="progress")
        assert any("Video 1/2 completado" in message for message in messages)
        assert any("Video 2/2 completado" in message for message in messages)
        assert len(json.loads(session.state["youtube_comments_collected"])) == 2

    asyncio.run(scenario())


def test_classifier_timeout_is_bounded_and_preserves_checkpoint():
    async def never_returns(**_kwargs):
        await asyncio.Event().wait()

    with patch("marketing_campaign_agent.comments_pipeline.CLASSIFICATION_REQUEST_TIMEOUT_SECONDS", 1):
        state, messages, _, _, client = asyncio.run(run_pipeline(
            [[video("a", ["a"])]], never_returns))
    assert client.aio.models.generate_content.call_count == 4
    assert state["youtube_comments_checkpoint"]["result_count"] == 1
    assert state["youtube_comments_classification_status"]["status"] == "complete"
    assert state["youtube_comments_classification_status"]["technical_error_count"] == 1
    assert state["youtube_comments_recovery"]["stop_reason"] == "attempts_exhausted"
    assert any("Lote 1 guardado" in message for message in messages)


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


def test_adaptive_recovery_splits_structural_batch_failure():
    ids = [str(i) for i in range(25)]

    def model(**kw):
        batch = json.loads(kw['contents'].split('COMENTARIOS=', 1)[1])
        if len(batch) > 5:
            return MagicMock(text='[]')
        return response([item['comment_id'] for item in batch])

    with patch('marketing_campaign_agent.comments_pipeline.COMMENTS_ADAPTIVE_RECOVERY', True):
        state, _, _, _, client = asyncio.run(run_pipeline([[video('a', ids)]], model))

    rows = json.loads(state['youtube_comments_classified'])
    recovery = state['youtube_comments_classification_status']['adaptive_recovery']
    assert len(rows) == 25
    assert len({row['comment_id'] for row in rows}) == 25
    assert recovery['full_batch_failures'] == 1
    assert recovery['sub_batches_requested'] == 5
    assert recovery['singleton_requests'] == 0
    assert state['youtube_comments_classification_status']['technical_error_count'] == 0
    assert client.models.generate_content.call_count == 6


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


def test_final_recovery_isolates_category_mismatch_to_single_comments():
    ids = [str(i) for i in range(5)]
    batch_sizes = []

    def model(**kwargs):
        batch = json.loads(kwargs["contents"].split("COMENTARIOS=", 1)[1].split("\nREINTENTO:", 1)[0])
        batch_sizes.append(len(batch))
        if len(batch) > 1:
            return MagicMock(text=json.dumps([{
                "comment_id": item["comment_id"], "decision": "deseo", "category_id": "P1",
            } for item in batch]))
        return response([batch[0]["comment_id"]], "no_aplica")

    state, _, _, _, _ = asyncio.run(run_pipeline([[video("a", ids)]], model))
    rows = json.loads(state["youtube_comments_classified"])
    assert batch_sizes[-5:] == [1, 1, 1, 1, 1]
    assert len(rows) == 5
    assert all(item["decision"] == "no_aplica" for item in rows)
    assert state["youtube_comments_classification_status"]["technical_error_count"] == 0


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


def test_rate_limit_opens_circuit_and_does_not_send_every_batch():
    class RateLimited(Exception):
        code = 429

    ids = [str(i) for i in range(51)]
    state, _, _, _, client = asyncio.run(run_pipeline(
        [[video('a', ids)]], RateLimited('quota exceeded')))

    rows = json.loads(state['youtube_comments_classified'])
    assert len(rows) == 51
    assert client.models.generate_content.call_count == 4
    assert all('COBERTURA_BUSQUEDA=' not in call.kwargs['contents']
               and 'DESEOS=' not in call.kwargs['contents']
               and 'PROBLEMAS=' not in call.kwargs['contents']
               for call in client.models.generate_content.call_args_list)
    assert state['youtube_comments_classification_status']['technical_error_count'] == 51
    assert state['youtube_comments_recovery']['stop_reason'] == 'rate_limited'
    assert rows[0]['failure']['error_code'] == 429
    assert rows[0]['failure']['retry_after'] == 60


def test_threshold_during_recovery_completes_source_before_deciding():
    def model(**kw):
        batch = json.loads(kw['contents'].split('COMENTARIOS=')[1])
        return MagicMock(text='[]') if len(batch) > 10 else response([x['comment_id'] for x in batch])
    with patch('marketing_campaign_agent.comments_pipeline.CLASSIFICATION_TARGET', 10):
        state, messages, _, _, client = asyncio.run(run_pipeline([[video('a', [str(x) for x in range(25)])]], model))
    assert client.models.generate_content.call_count == 4
    assert state['youtube_comments_classification_status']['target_reached']
    assert len(json.loads(state['youtube_comments_classified'])) == 25
    assert state['market_research_metrics']['processing_status'] == 'THRESHOLD_REACHED'
    assert state['market_research_metrics']['decision'] == 'ACCEPT_OFFER'
    assert state['market_research_metrics']['summary']['status'] == 'APPROVED'
    assert 'umbral combinado' in state['market_research_metrics']['conclusion']
    assert not any('INCOMPLETE_ANALYSIS' in message for message in messages)
    assert any('ACCEPT OFFER' in message for message in messages)


def test_only_combined_threshold_is_evaluated_after_full_classification():
    ids = [str(i) for i in range(125)]

    def model(**kwargs):
        batch = json.loads(kwargs['contents'].split('COMENTARIOS=', 1)[1])
        decision = 'deseo' if int(batch[0]['comment_id']) < 50 else 'problema'
        return response([item['comment_id'] for item in batch], decision)

    with patch('marketing_campaign_agent.comments_pipeline.CLASSIFICATION_BATCH_SIZE', 25), \
            patch('marketing_campaign_agent.comments_pipeline.CLASSIFICATION_CONCURRENCY', 1):
        state, messages, _, _, client = asyncio.run(run_pipeline([[video('a', ids)]], model))

    rows = json.loads(state['youtube_comments_classified'])
    assert len(rows) == 125
    assert client.models.generate_content.call_count == 5
    assert state['youtube_comments_classification_status']['target_reached']
    assert state['market_research_metrics']['processing_status'] == 'THRESHOLD_REACHED'
    assert not _market_signal_reached_counts(51, 0, 100)
    assert not _market_signal_reached_counts(50, 49, 100)
    assert _market_signal_reached_counts(51, 49, 100)
    assert _market_signal_reached_counts(30, 70, 100)
    assert _market_signal_reached_counts(0, 100, 100)
    assert not any('en paralelo' in message for message in messages if 'Clasificando lote' in message)


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
    assert eligible_for_restart({
        'pipeline_run': {'status': 'active', 'stage': 1},
        'landing_page_research': json.dumps(RESEARCH),
        'youtube_videos_research': json.dumps([{'video_id': 'saved'}]),
        'youtube_search_status': {'status': 'validating'},
    })


def test_orchestrator_resumes_video_validation_before_comment_stages():
    async def scenario():
        saved = [{"video_id": "saved", "video_href": "https://youtube.com/watch?v=saved",
                  "relevance_decision": "accepted", "detected_language": "es"}]
        stages = [
            Stage(name="landing", seed=True),
            Stage(name="YoutubeCommentsAnalyzer", video_candidates=saved, search_status={
                "status": "complete", "query_count": 12, "completed_queries": 12,
                "query_error_count": 0, "candidate_count": 1, "candidates_decided": 1,
                "candidates_review": 0, "accepted": 1, "rejected": 0,
            }),
            Stage(name="collector"), Stage(name="classifier"), Stage(name="report"),
        ]
        initial = {
            STATUS_KEY: {"status": "validated", "invocation_id": "old"},
            "landing_page_research": json.dumps(RESEARCH),
            "youtube_videos_research": json.dumps(saved),
            "youtube_search_status": {"status": "validating", "candidate_count": 2,
                                      "candidates_decided": 1},
            "pipeline_run": {"status": "active", "stage": 1, "restart_attempts": 0},
        }
        service = InMemorySessionService()
        await service.create_session(app_name="test", user_id="u", session_id="video-resume",
                                     state=initial)
        root = GroundedCampaignOrchestrator(name="pipeline", sub_agents=stages)
        runner = Runner(agent=root, app_name="test", session_service=service)
        events = [event async for event in runner.run_async(
            user_id="u", session_id="video-resume",
            new_message=types.Content(role="user", parts=[types.Part.from_text(text="reanuda")]))]
        state = (await service.get_session(
            app_name="test", user_id="u", session_id="video-resume")).state
        messages = [part.text for event in events if event.content
                    for part in event.content.parts or [] if part.text]
        assert [stage.calls for stage in stages] == [0, 1, 1, 1, 1]
        assert state["video_analysis_resume"] is True
        assert any("Reanudando la validación de videos" in message for message in messages)

    asyncio.run(scenario())


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


def test_closed_event_stream_is_not_left_active():
    async def scenario():
        class WaitingStage(BaseAgent):
            async def _run_async_impl(self, ctx):
                await asyncio.Event().wait()
                yield

        root = GroundedCampaignOrchestrator(
            name='closed_stream_root', sub_agents=[WaitingStage(name='waiting')])
        service = InMemorySessionService()
        await service.create_session(app_name='test', user_id='u', session_id='closed')
        runner = Runner(agent=root, app_name='test', session_service=service)
        stream = runner.run_async(
            user_id='u', session_id='closed', new_message=types.Content(
                role='user', parts=[types.Part.from_text(text='https://example.com')]))
        await anext(stream)
        await stream.aclose()
        state = (await service.get_session(
            app_name='test', user_id='u', session_id='closed')).state
        assert state['pipeline_run']['status'] == 'cancelled'

    asyncio.run(scenario())


def test_consolidation_merges_duplicate_videos_and_threads_without_losing_text():
    first = video("a", ["a"])
    second = video("a", ["a", "b"])
    result, stats = _consolidate_videos([first, second])
    assert len(result) == 1
    assert [x["comment_id"] for x in result[0]["3_months_comments"]] == ["a", "b"]
    assert stats["duplicate_videos"] == 1
    assert stats["duplicate_comments"] == 1
