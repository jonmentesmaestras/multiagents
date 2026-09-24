import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from marketing_campaign_agent.comments_pipeline import (
    BatchedVideoAnalyzerAgent, VIDEO_VALIDATION_CONTRACT_VERSION,
)


def candidate(index):
    video_id = f"vid{index:08d}"
    return {
        "video_id": video_id,
        "video_href": f"https://www.youtube.com/watch?v={video_id}",
        "video_title": f"La biodescodificación de síntomas en español {index}",
        "video_description": "Explica el origen emocional de un síntoma.",
        "channel_title": "Canal en español",
        "default_language": "es",
        "audio_language": "es",
        "video_views": f"{index} views",
        "view_count": index * 30000,
        "comment_count": 150,
        "published_at": "2026-01-01T00:00:00Z",
    }


def decisions_from_prompt(contents=None, **kwargs):
    payload = contents.split("VIDEOS=", 1)[1].split("\nREINTENTO:", 1)[0]
    videos = json.loads(payload)
    return MagicMock(text=json.dumps([{
        "video_id": row["video_id"], "decision": "accepted", "language": "es",
        "reason": "Coincide con el mecanismo de la landing",
        "evidence": row["video_title"],
    } for row in videos]))


async def run_analyzer(search_side_effect, model_side_effect, landing=None, initial=None):
    landing = landing or {
        "offer": {"description": "Guía de biodescodificación"},
        "main_promise": "Comprender el origen emocional de síntomas",
        "avatar": {"name": "Personas interesadas en biodescodificación"},
        "deseos": ["Comprender", "Sentir alivio", "Liberar emociones"],
        "problemas": ["Migrañas", "Ansiedad", "Emociones reprimidas"],
        "youtube_keywords": ["biodescodificación migrañas", "biodescodificación ansiedad"],
    }
    service = InMemorySessionService()
    state = {"landing_page_research": json.dumps(landing), **(initial or {})}
    await service.create_session(app_name="test", user_id="u", session_id="s", state=state)
    agent = BatchedVideoAnalyzerAgent(name="YoutubeCommentsAnalyzer", model="offline", tools=[])
    runner = Runner(agent=agent, app_name="test", session_service=service)
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(side_effect=model_side_effect)
    with patch("marketing_campaign_agent.comments_pipeline.search_and_collect_youtube_data",
               side_effect=search_side_effect) as search, \
            patch("google.genai.Client", return_value=client):
        events = [event async for event in runner.run_async(
            user_id="u", session_id="s",
            new_message=types.Content(role="user", parts=[types.Part.from_text(text="run")]))]
    session = await service.get_session(app_name="test", user_id="u", session_id="s")
    return session.state, events, search, client


def fashion_landing():
    return {
        "offer": {"description": "Creación de fotos de productos de moda con IA",
                  "deliverables": ["Prompts para ropa y calzado"]},
        "main_promise": "Crear fotos profesionales para catálogos de moda",
        "avatar": {"name": "Tiendas de ropa", "description": "Vendedores de moda y e-commerce"},
        "deseos": ["Mostrar prendas", "Crear catálogos", "Mejorar fotos de productos"],
        "problemas": ["Fotos poco profesionales", "No contratar modelos", "Mostrar la caída de la ropa"],
        "youtube_keywords": ["prompts de inteligencia artificial para fotos de catalogo"],
    }


def test_queries_are_separate_and_validation_uses_batches_of_ten():
    rows = [candidate(index) for index in range(23)]
    state, events, search, client = asyncio.run(run_analyzer(
        lambda query, **kwargs: rows,
        decisions_from_prompt,
    ))

    assert search.call_count == 2
    assert [call.args[0] for call in search.call_args_list] == [
        "biodescodificación migrañas", "biodescodificación ansiedad"]
    assert all(call.kwargs == {"min_views": 0, "max_results_per_keyword": 50}
               for call in search.call_args_list)
    assert client.aio.models.generate_content.call_count == 3
    batch_sizes = [len(json.loads(call.kwargs["contents"].split("VIDEOS=", 1)[1]))
                   for call in client.aio.models.generate_content.call_args_list]
    assert batch_sizes == [10, 10, 3]
    assert all(call.kwargs["config"].temperature == 0
               and call.kwargs["config"].seed == 17
               and call.kwargs["config"].candidate_count == 1
               for call in client.aio.models.generate_content.call_args_list)
    assert state["youtube_search_status"]["status"] == "complete"
    assert state["youtube_search_status"]["candidate_count"] == 23
    assert state["youtube_search_status"]["candidates_decided"] == 23
    saved = json.loads(state["youtube_videos_research"])
    assert len(saved) == 23
    assert next(item for item in saved if item["video_id"] == candidate(0)["video_id"])[
        "relevance_decision"] == "accepted"  # 25,000 views is not a hard floor.
    texts = [part.text for event in events if event.content for part in event.content.parts or []]
    assert not any(text.lstrip().startswith("[") for text in texts)


def test_truncated_json_retries_only_the_failed_batch():
    rows = [candidate(index) for index in range(11)]
    calls = 0

    def model(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return MagicMock(text='[{"video_id": "truncated"')
        return decisions_from_prompt(kwargs["contents"])

    state, _, _, client = asyncio.run(run_analyzer(lambda query, **kwargs: rows, model))

    assert client.aio.models.generate_content.call_count == 3
    assert state["youtube_search_status"]["status"] == "complete"
    assert state["youtube_search_status"]["candidate_count"] == 11
    assert state["youtube_search_status"]["candidates_decided"] == 11


def test_comment_floor_is_applied_before_semantic_validation():
    rows = [candidate(0), candidate(1)]
    rows[0]["comment_count"] = 100
    state, _, _, client = asyncio.run(run_analyzer(
        lambda query, **kwargs: rows,
        decisions_from_prompt,
    ))

    assert client.aio.models.generate_content.call_count == 1
    saved = json.loads(state["youtube_videos_research"])
    low = next(item for item in saved if item["video_id"] == rows[0]["video_id"])
    high = next(item for item in saved if item["video_id"] == rows[1]["video_id"])
    assert low["relevance_decision"] == "rejected"
    assert low["selection_reason"] == "below_comment_threshold"
    assert high["relevance_decision"] == "accepted"
    assert state["youtube_search_status"]["status"] == "complete"


def test_popularity_then_numeric_filter_then_spanish_title_review():
    landing = {
        "offer": {"description": "Comunicación intuitiva con animales"},
        "main_promise": "Entender mensajes de mascotas",
        "avatar": {"name": "Personas con mascotas", "description": "Cuidadores de animales"},
        "deseos": ["Conectar con mascotas"], "problemas": ["No entender sus emociones"],
        "youtube_keywords": ["cómo hablar con mascotas"],
        "youtube_search_specs": [{
            "query": "cómo hablar con mascotas", "context_terms": ["animales"],
            "intent_terms": ["mensajes"],
        }],
    }
    relevant = {**candidate(70), "video_title": (
        "HAZ ESTO para CONECTAR y HABLAR con tus MASCOTAS de este PLANO y las que YA NO ESTÁN"),
        "view_count": 275084, "comment_count": 1534}
    unrelated = {**candidate(71), "video_title": (
        "Así puedes ABRIR TU TERCER OJO | Iván Donalson #14"),
        "view_count": 150000, "comment_count": 800}
    low_comments = {**candidate(72), "video_title": "La comunicación con animales",
                    "view_count": 900000, "comment_count": 100}
    english = {**candidate(73), "video_title": (
        "How to Send a Telepathic Message to a Specific Person"),
        "default_language": "en", "audio_language": "en",
        "view_count": 500000, "comment_count": 1200}
    state, _, _, client = asyncio.run(run_analyzer(
        lambda query, **kwargs: [unrelated, low_comments, relevant, english],
        decisions_from_prompt, landing))
    assert client.aio.models.generate_content.call_count == 1
    prompted = json.loads(
        client.aio.models.generate_content.call_args.kwargs["contents"].split("VIDEOS=", 1)[1])
    assert [row["video_id"] for row in prompted] == [relevant["video_id"], unrelated["video_id"]]
    saved = {item["video_id"]: item for item in json.loads(state["youtube_videos_research"])}
    assert saved[relevant["video_id"]]["relevance_decision"] == "accepted"
    assert saved[unrelated["video_id"]]["selection_reason"] == "insufficient_landing_context"
    assert saved[low_comments["video_id"]]["selection_reason"] == "below_comment_threshold"
    assert saved[english["video_id"]]["selection_reason"] == "non_spanish_title"


def test_unknown_comment_count_is_pending_when_metadata_recovery_failed():
    rows = [candidate(0)]
    rows[0].pop("comment_count")
    rows[0]["view_count"] = "unknown"
    state, _, _, client = asyncio.run(run_analyzer(
        lambda query, **kwargs: rows,
        decisions_from_prompt,
    ))

    assert client.aio.models.generate_content.call_count == 0
    saved = json.loads(state["youtube_videos_research"])[0]
    assert saved["relevance_decision"] == "requires_review"
    assert saved["selection_reason"] == "comment_count_unknown"
    assert state["youtube_search_status"]["status"] == "incomplete"
    assert state["youtube_search_status"]["candidates_decided"] == 0
    assert state["youtube_search_status"]["candidates_review"] == 1


def test_generic_prompt_title_without_description_is_rejected():
    row = candidate(50)
    row["video_title"] = "Este es el Secreto para Crear el Mejor Prompt de Todos #ia #prompts #chatgpt"
    row["video_description"] = ""

    def model(**kwargs):
        return MagicMock(text=json.dumps([{
            "video_id": row["video_id"], "decision": "accepted", "language": "es",
            "reason": "Habla de prompts de inteligencia artificial",
            "evidence": row["video_title"],
        }]))

    state, _, _, _ = asyncio.run(run_analyzer(
        lambda query, **kwargs: [row], model, fashion_landing()))

    saved = json.loads(state["youtube_videos_research"])[0]
    assert saved["relevance_decision"] == "rejected"
    assert saved["selection_reason"] == "insufficient_landing_context"


def test_generic_title_is_not_rescued_by_relevant_description():
    row = candidate(51)
    row["video_title"] = "Este es el Secreto para Crear el Mejor Prompt de Todos"
    row["video_description"] = (
        "Crea fotos de ropa y calzado para catálogos de e-commerce con inteligencia artificial."
    )

    def model(**kwargs):
        return MagicMock(text=json.dumps([{
            "video_id": row["video_id"], "decision": "accepted", "language": "es",
            "reason": "La descripción confirma el uso para productos de moda",
            "evidence": row["video_description"],
        }]))

    state, _, _, _ = asyncio.run(run_analyzer(
        lambda query, **kwargs: [row], model, fashion_landing()))

    saved = json.loads(state["youtube_videos_research"])[0]
    assert saved["relevance_decision"] == "rejected"
    assert saved["selection_reason"] == "insufficient_landing_context"


def test_missing_evidence_is_resolved_per_video_without_stopping_coverage():
    rejected, unsupported_acceptance = candidate(60), candidate(61)

    def model(**kwargs):
        return MagicMock(text=json.dumps([
            {"video_id": rejected["video_id"], "decision": "rejected",
             "language": "es", "reason": "No corresponde a la landing"},
            {"video_id": unsupported_acceptance["video_id"], "decision": "accepted",
             "language": "es", "reason": "Coincide con la landing"},
        ]))

    state, _, _, client = asyncio.run(run_analyzer(
        lambda query, **kwargs: [rejected, unsupported_acceptance], model))

    saved = {item["video_id"]: item for item in json.loads(state["youtube_videos_research"])}
    assert state["youtube_search_status"]["status"] == "complete"
    assert state["youtube_search_status"]["candidates_review"] == 0
    assert client.aio.models.generate_content.call_count == 1
    assert saved[rejected["video_id"]]["relevance_evidence"] == rejected["video_title"]
    assert saved[unsupported_acceptance["video_id"]]["relevance_decision"] == "rejected"
    assert saved[unsupported_acceptance["video_id"]]["selection_reason"] == "missing_relevance_evidence"


def test_resume_reuses_saved_decisions_and_validates_only_pending_candidates():
    rows = [candidate(index) for index in range(15)]
    saved = [{**item, "relevance_decision": "accepted", "detected_language": "es",
              "relevance_reason": "Decisión guardada", "relevance_evidence": item["video_title"],
              "video_keywords": "biodescodificación migrañas",
              "validation_contract_version": VIDEO_VALIDATION_CONTRACT_VERSION}
             for item in rows[:10]]
    state, _, _, client = asyncio.run(run_analyzer(
        lambda query, **kwargs: rows,
        decisions_from_prompt,
        initial={"video_analysis_resume": True,
                 "youtube_videos_research": json.dumps(saved)}))

    assert client.aio.models.generate_content.call_count == 1
    pending_batch = json.loads(
        client.aio.models.generate_content.call_args.kwargs["contents"].split("VIDEOS=", 1)[1])
    assert {item["video_id"] for item in pending_batch} == {
        item["video_id"] for item in rows[10:]}
    assert state["youtube_search_status"]["status"] == "complete"
    assert state["youtube_search_status"]["resume_saved_count"] == 10
    assert len(json.loads(state["youtube_videos_research"])) == 15


def test_resume_rechecks_old_keyword_gate_rejection():
    row = candidate(80)
    old = {**row, "relevance_decision": "rejected",
           "selection_reason": "keyword_context_mismatch",
           "validation_contract_version": VIDEO_VALIDATION_CONTRACT_VERSION - 1}
    state, _, _, client = asyncio.run(run_analyzer(
        lambda query, **kwargs: [row], decisions_from_prompt,
        initial={"video_analysis_resume": True,
                 "youtube_videos_research": json.dumps([old])}))
    assert client.aio.models.generate_content.call_count == 1
    saved = json.loads(state["youtube_videos_research"])[0]
    assert saved["relevance_decision"] == "accepted"
    assert saved["validation_contract_version"] == VIDEO_VALIDATION_CONTRACT_VERSION


def test_video_validation_request_has_end_to_end_timeout():
    async def never_returns(**kwargs):
        await asyncio.Event().wait()

    with patch("marketing_campaign_agent.comments_pipeline.VIDEO_VALIDATION_ATTEMPTS", 1), \
            patch("marketing_campaign_agent.comments_pipeline.VIDEO_VALIDATION_REQUEST_TIMEOUT_SECONDS", 1):
        state, _, _, client = asyncio.run(run_analyzer(
            lambda query, **kwargs: [candidate(99)], never_returns))

    assert client.aio.models.generate_content.call_count == 1
    assert state["youtube_search_status"]["status"] == "incomplete"
    saved = json.loads(state["youtube_videos_research"])
    assert saved[0]["relevance_decision"] == "requires_review"
    assert saved[0]["validation_failure_kind"] == "technical_error"
