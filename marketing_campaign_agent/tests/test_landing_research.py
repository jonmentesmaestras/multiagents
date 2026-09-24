"""Regression tests: use the real async ADK Runner without external API calls."""

import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from marketing_campaign_agent.instructions import LANDING_PAGE_COPYWRITER_INSTRUCTION
from marketing_campaign_agent.landing_research import (
    GroundedCampaignOrchestrator, GroundedLandingPageAgent, STATUS_KEY, STATE_KEYS,
    KeywordLanguageError, current_source_only, requested_url, validate_research,
)
from marketing_campaign_agent.tools import landing_page_scraper as scraper
from marketing_campaign_agent.landing_attachments import WAITING_ATTACHMENT


URL = "https://www.musicofwisdom.com/100frequencies"
COPY = (
    "Download the 100 Frequencies for Healing PDF Guide. "
    "Get 8 days of email tutorials and free music to apply the frequencies in daily life. "
    "Explore relaxation, focus, creativity, deep sleep and emotional balance."
)
JAVASCRIPT_SHELL = (
    "This site requires JavaScript\n"
    "To view this website, enable JavaScript in your browser settings and reload the page.\n"
    "Reload page"
)
SOURCE = {
    "url": URL, "requested_url": URL, "title": "100 Frequencies for Healing",
    "suggested_page_type": "TSL", "page_language": "en", "main_content": COPY,
}


def valid_analysis():
    fields = ["offer.description", "offer.deliverables.0", "main_promise", "avatar"]
    fields += [f"{key}.{i}" for key, n in (("deseos", 3), ("problemas", 3),
                                         ("youtube_keywords", 12)) for i in range(n)]
    return {
        "offer": {"description": "Guía PDF y tutoriales", "deliverables": ["Guía PDF"]},
        "avatar": {"name": "Personas interesadas en frecuencias", "description": "Buscan bienestar",
                   "demographics": {"age_range": None, "gender": None, "language": None}},
        "main_promise": "Aprender a aplicar frecuencias en la vida diaria",
        "deseos": ["Relajación", "Concentración", "Descanso"],
        "problemas": ["Estrés", "Distracción", "Dificultad para descansar"],
        "youtube_keywords": [
            "cómo aplicar frecuencias", "guía de frecuencias para principiantes",
            "frecuencias para aliviar estrés", "frecuencias para mejorar concentración",
            "frecuencias para descansar", "frecuencias para relajación",
            "frecuencias para mantener el enfoque", "frecuencias para sueño profundo",
            "cómo usar frecuencias diariamente", "qué frecuencias ayudan al bienestar",
            "experiencias usando frecuencias", "testimonios sobre frecuencias de sanación",
        ],
        "evidence": [{"field": f, "quote": COPY,
                      "kind": "explicit" if f.startswith("offer.") or f == "main_promise"
                      else "inference"} for f in fields],
    }


class StubModel(BaseLlm):
    model: str = "offline-test"
    output: str | list[str]
    requests: list = Field(default_factory=list)
    partial_text: str | None = None

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request)
        if self.partial_text:
            yield LlmResponse(partial=True, content=types.Content(role="model", parts=[
                types.Part.from_text(text=self.partial_text)]))
        output = (self.output[min(len(self.requests) - 1, len(self.output) - 1)]
                  if isinstance(self.output, list) else self.output)
        yield LlmResponse(content=types.Content(role="model", parts=[
            types.Part.from_text(text=output)]))


class DownstreamAgent(BaseAgent):
    calls: int = 0

    async def _run_async_impl(self, ctx):
        self.calls += 1
        yield Event(author=self.name, invocation_id=ctx.invocation_id,
                    content=types.Content(role="model", parts=[types.Part.from_text(text="ok")]))


async def run_pipeline(source, output=None, initial_state=None, partial_text=None):
    model = StubModel(output=json.dumps(valid_analysis()) if output is None else output,
                      partial_text=partial_text)
    landing = GroundedLandingPageAgent(
        name="LandingPageResearcher", model=model,
        instruction=LANDING_PAGE_COPYWRITER_INSTRUCTION, output_key="landing_page_research",
        before_model_callback=current_source_only, include_contents="none",
    )
    downstream = [DownstreamAgent(name=f"downstream_{i}") for i in range(4)]
    root = GroundedCampaignOrchestrator(name="pipeline", sub_agents=[landing, *downstream])
    service = InMemorySessionService()
    await service.create_session(app_name="test", user_id="user", session_id="session",
                                 state=initial_state or {})
    runner = Runner(agent=root, app_name="test", session_service=service)
    with patch("marketing_campaign_agent.landing_research.scrape_landing_page",
               new=AsyncMock(return_value=source)) as scrape:
        events = [e async for e in runner.run_async(
            user_id="user", session_id="session",
            new_message=types.Content(role="user", parts=[types.Part.from_text(text=URL)]))]
    session = await service.get_session(app_name="test", user_id="user", session_id="session")
    return session, events, model, downstream, scrape


@pytest.mark.parametrize("source", [
    {"error": "Playwright failed", "url": URL},
    {**SOURCE, "main_content": ""},
    {**SOURCE, "title": "Just a moment..."},
    {**SOURCE, "title": "Imersão Reset Total | Life Reset",
     "main_content": JAVASCRIPT_SHELL, "extraction_method": "browser"},
    {**SOURCE, "requested_url": "https://wrong.example"},
])
def test_extraction_failure_stops_model_and_all_downstream_and_clears_stale_state(source):
    previous = {key: "OLD_LICENSE_RESEARCH" for key in STATE_KEYS}
    previous[STATUS_KEY] = {"status": "validated", "invocation_id": "old"}
    session, events, model, downstream, scrape = asyncio.run(run_pipeline(source, initial_state=previous))
    scrape.assert_awaited_once_with(URL)
    assert not model.requests
    assert all(a.calls == 0 for a in downstream)
    assert all(session.state.get(key) is None for key in STATE_KEYS)
    wrong_url = source.get("requested_url") == "https://wrong.example"
    assert session.state[STATUS_KEY]["status"] == ("error" if wrong_url else WAITING_ATTACHMENT)
    messages = [p.text for event in events if event.content for p in event.content.parts or [] if p.text]
    assert ("Investigación detenida" if wrong_url else "Adjunta aquí un PDF") in messages[-1]
    if not wrong_url:
        assert session.state['pipeline_run']['status'] == WAITING_ATTACHMENT


def test_lifereset_javascript_shell_requests_pdf_with_auditable_status():
    source = {
        **SOURCE, "title": "Imersão Reset Total | Life Reset",
        "main_content": JAVASCRIPT_SHELL, "extraction_method": "browser",
    }
    session, events, model, downstream, _ = asyncio.run(run_pipeline(source))
    status = session.state[STATUS_KEY]
    assert status["status"] == WAITING_ATTACHMENT
    assert status["error_code"] == "landing_content_unavailable"
    assert status["error_stage"] == "extraction"
    assert status["extraction_method"] == "browser"
    assert status["source_word_count"] == 20
    assert status["next_action"] == "attach_pdf_or_images"
    assert session.state["pipeline_run"]["status"] == WAITING_ATTACHMENT
    assert not model.requests and not any(agent.calls for agent in downstream)
    messages = [part.text for event in events if event.content
                for part in event.content.parts or [] if part.text]
    assert any("Adjunta aquí un PDF o capturas" in message for message in messages)


def test_success_publishes_validated_current_source_and_runs_downstream():
    session, events, model, downstream, _ = asyncio.run(run_pipeline(SOURCE))
    assert len(model.requests) == 1
    sent = model.requests[0].contents
    assert len(sent) == 1 and COPY in sent[0].parts[0].text
    assert all(a.calls == 1 for a in downstream)
    result = json.loads(session.state["landing_page_research"])
    assert result["source_info"]["url"] == URL
    assert result["source_info"]["page_language"] == "en"
    assert result["source_info"]["youtube_language"] == "es"
    assert result["avatar"]["demographics"]["age_range"] is None
    assert session.state[STATUS_KEY]["status"] == "validated"


def test_orchestrator_rejects_validated_status_from_another_invocation():
    async def scenario():
        first, youtube = DownstreamAgent(name="first"), DownstreamAgent(name="youtube")
        root = GroundedCampaignOrchestrator(name="pipeline", sub_agents=[first, youtube])
        service = InMemorySessionService()
        await service.create_session(app_name="test", user_id="user", session_id="session", state={
            STATUS_KEY: {"status": "validated", "invocation_id": "previous-invocation"},
            "landing_page_research": json.dumps(valid_analysis()),
        })
        runner = Runner(agent=root, app_name="test", session_service=service)
        async for _ in runner.run_async(user_id="user", session_id="session",
                                       new_message=types.Content(role="user", parts=[types.Part.from_text(text=URL)])):
            pass
        assert first.calls == 1 and youtube.calls == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("bad_output,expected_calls,expected_status", [
    ("not json", 2, "error"),
    ('{"error": "No evidence"}', 1, WAITING_ATTACHMENT),
    ('{"main_promise": "Commercial licensing"}', 2, "error"),
])
def test_invalid_model_output_is_never_published_or_used(
        bad_output, expected_calls, expected_status):
    session, events, model, downstream, _ = asyncio.run(run_pipeline(
        SOURCE, output=bad_output, partial_text="UNVERIFIED_STREAM"))
    assert len(model.requests) == expected_calls
    assert all(a.calls == 0 for a in downstream)
    assert session.state["landing_page_research"] is None
    assert session.state[STATUS_KEY]["status"] == expected_status
    assert session.state["pipeline_run"]["status"] == (
        WAITING_ATTACHMENT if expected_status == WAITING_ATTACHMENT else "failed")
    assert not any("UNVERIFIED_STREAM" in (p.text or "")
                   for e in events if e.content for p in e.content.parts or [])


def test_structural_repair_can_recover_valid_web_analysis():
    session, _, model, downstream, _ = asyncio.run(run_pipeline(
        SOURCE, output=['{"main_promise":"incompleto"}', json.dumps(valid_analysis())]))
    assert len(model.requests) == 2
    assert session.state[STATUS_KEY]["status"] == "validated"
    assert session.state[STATUS_KEY]["repair_attempts"] == 1
    assert all(agent.calls == 1 for agent in downstream)
    repair = model.requests[1].contents[0].parts[0].text
    assert "CORRECCIÓN OBLIGATORIA" in repair
    assert '"repair_type": "structure"' in repair


def test_fabricated_quote_and_missing_evidence_are_rejected():
    data = valid_analysis()
    data["evidence"][0]["quote"] = "Unlimited royalty-free commercial licensing"
    with pytest.raises(ValueError, match="no coinciden"):
        validate_research(json.dumps(data), SOURCE)
    data = valid_analysis()
    data["evidence"] = [item for item in data["evidence"]
                        if item["field"] != "problemas.2"]
    with pytest.raises(ValueError, match="Falta evidencia"):
        validate_research(json.dumps(data), SOURCE)


def test_derived_youtube_keywords_do_not_require_literal_quotes():
    data = valid_analysis()
    for item in data["evidence"]:
        if item["field"].startswith("youtube_keywords."):
            item["quote"] = "Consulta derivada en español que no aparece literalmente"
    assert validate_research(json.dumps(data), SOURCE)["youtube_keywords"] == data["youtube_keywords"]

    data["evidence"] = [item for item in data["evidence"]
                        if not item["field"].startswith("youtube_keywords.")]
    assert validate_research(json.dumps(data), SOURCE)["youtube_keywords"] == data["youtube_keywords"]


def test_generic_search_spec_terms_are_removed_without_stopping_research():
    data = valid_analysis()
    data["youtube_search_specs"] = [
        {"query": query, "context_terms": ["frecuencias"],
         "intent_terms": ["aplicar"]}
        for query in data["youtube_keywords"]
    ]
    data["youtube_search_specs"][0]["context_terms"] = ["método", "frecuencias"]
    data["youtube_search_specs"][0]["intent_terms"] = ["método"]
    result = validate_research(json.dumps(data), SOURCE)
    assert result["youtube_search_specs"][0]["context_terms"] == ["frecuencias"]
    assert result["youtube_search_specs"][0]["intent_terms"] == ["aplicar frecuencias"]


def test_all_weak_search_spec_terms_fall_back_to_grounded_query():
    data = valid_analysis()
    data["youtube_search_specs"] = [
        {"query": query, "context_terms": ["método"], "intent_terms": ["método"]}
        for query in data["youtube_keywords"]
    ]
    result = validate_research(json.dumps(data), SOURCE)
    assert result["youtube_search_specs"][0]["context_terms"] == ["aplicar frecuencias"]
    assert result["youtube_search_specs"][0]["intent_terms"] == ["aplicar frecuencias"]
    assert all(spec["context_terms"] and spec["intent_terms"]
               for spec in result["youtube_search_specs"])


def test_generic_spec_does_not_stop_orchestrated_landing_stage():
    data = valid_analysis()
    data["youtube_search_specs"] = [
        {"query": query, "context_terms": ["método"], "intent_terms": ["método"]}
        for query in data["youtube_keywords"]
    ]
    session, _, model, downstream, _ = asyncio.run(run_pipeline(
        SOURCE, output=json.dumps(data)))
    assert len(model.requests) == 1
    assert session.state[STATUS_KEY]["status"] == "validated"
    assert all(agent.calls == 1 for agent in downstream)


def test_youtube_query_matrix_requires_exactly_twelve_entries():
    data = valid_analysis()
    data["youtube_keywords"] = data["youtube_keywords"][:10]
    with pytest.raises(ValueError):
        validate_research(json.dumps(data), SOURCE)


def test_ambiguous_youtube_query_without_landing_anchor_is_rejected():
    data = valid_analysis()
    data["youtube_keywords"][0] = "cómo evitar problemas y mejorar resultados"
    with pytest.raises(ValueError, match="Búsquedas ambiguas"):
        validate_research(json.dumps(data), SOURCE)


def test_exact_landing_title_is_a_valid_testimonial_search_anchor():
    data = valid_analysis()
    data["youtube_keywords"][0] = (
        "protocolo venda em dólar opiniones y testimonios de alumnos"
    )
    source = {**SOURCE, "title": "Protocolo Venda em Dólar"}
    result = validate_research(json.dumps(data), source)
    assert result["youtube_keywords"][0] == data["youtube_keywords"][0]


def test_grounded_portuguese_brand_name_is_allowed_inside_spanish_query():
    data = valid_analysis()
    data["offer"]["description"] = (
        "Programa Imersão Reset Total conducido por Gabi Morais")
    data["youtube_keywords"][0] = (
        "testimonios Imersão Reset Total Gabi Morais")
    source = {
        **SOURCE,
        "main_content": COPY + " La oferta se llama Imersão Reset Total por Gabi Morais.",
    }
    result = validate_research(json.dumps(data), source)
    assert result["youtube_keywords"][0] == data["youtube_keywords"][0]


def test_mixed_portuguese_youtube_queries_are_rejected_before_search():
    data = valid_analysis()
    data["youtube_keywords"][0] = "curso de harmonização facial com preenchimento"
    with pytest.raises(KeywordLanguageError, match="completamente en español"):
        validate_research(json.dumps(data), SOURCE)


def test_agent_repairs_foreign_query_language_once_before_publishing():
    mixed = valid_analysis()
    mixed["youtube_keywords"][0] = "curso de harmonização com preenchimento"
    session, _, model, downstream, _ = asyncio.run(run_pipeline(
        SOURCE, output=[json.dumps(mixed), json.dumps(valid_analysis())]))
    assert len(model.requests) == 2
    assert "CORRECCIÓN OBLIGATORIA" in model.requests[1].contents[0].parts[0].text
    assert session.state["landing_page_research"] is not None
    assert session.state["landing_page_research_status"]["status"] == "validated"
    assert all(agent.calls == 1 for agent in downstream)


def test_keyword_repair_keeps_search_specs_aligned_with_repaired_query():
    mixed = valid_analysis()
    mixed["youtube_keywords"][0] = "curso de harmonização com preenchimento"
    mixed["youtube_search_specs"] = [
        {"query": query, "context_terms": ["frecuencias"],
         "intent_terms": ["aplicar"]}
        for query in mixed["youtube_keywords"]
    ]
    session, _, model, downstream, _ = asyncio.run(run_pipeline(
        SOURCE, output=[json.dumps(mixed), json.dumps(valid_analysis())]))
    assert len(model.requests) == 2
    assert session.state[STATUS_KEY]["status"] == "validated"
    research = json.loads(session.state["landing_page_research"])
    assert research["youtube_search_specs"][0]["query"] == research["youtube_keywords"][0]
    assert research["youtube_search_specs"][0]["context_terms"] == ["aplicar frecuencias"]
    assert all(agent.calls == 1 for agent in downstream)


def test_demographics_require_explicit_evidence():
    data = valid_analysis()
    data["avatar"]["demographics"]["age_range"] = "25-55"
    with pytest.raises(ValueError, match="age_range"):
        validate_research(json.dumps(data), SOURCE)


def test_source_identity_is_not_taken_from_model():
    data = valid_analysis()
    data["source_info"] = {"url": "https://invented.example", "page_language": "es"}
    assert validate_research(json.dumps(data), SOURCE)["source_info"]["url"] == URL


def test_parser_excludes_navigation_and_footer():
    html = f'<html lang="en"><body><nav><h1>Commercial music</h1></nav><main><h1>Guide</h1><p>{COPY}</p></main><footer><p>Unlimited licenses</p></footer></body></html>'
    result = scraper.extract_landing_content(html, URL, "Guide")
    assert COPY in result["main_content"]
    assert "licenses" not in result["main_content"]
    assert not any("Commercial" in h["text"] for h in result["headings"])
    assert result["page_language"] == "en"


def test_parser_separates_biography_and_keeps_div_span_offer_copy_without_comments():
    html = f"""<html><head><title>Site branding</title></head><body>
        <h1>Guide</h1><!--$--><div><span>{COPY}</span></div><!--/$-->
        <h2>Meet Your Instructor</h2><p>Composer sells commercial music licenses.</p>
        <h2>Frequently Asked Questions</h2><div>The guide is free.</div>
        </body></html>"""
    result = scraper.extract_landing_content(html, URL, "Guide")
    assert COPY in result["main_content"]
    assert "licenses" not in result["main_content"]
    assert "licenses" in result["secondary_content"]
    assert "The guide is free" in result["main_content"]
    assert "$" not in result["main_content"]
    assert "Site branding" not in result["main_content"]


def test_javascript_shell_is_rejected_even_at_twenty_words():
    assert len(JAVASCRIPT_SHELL.split()) == 20
    error = scraper.content_error("Imersão Reset Total | Life Reset", JAVASCRIPT_SHELL)
    assert error


def test_browser_waits_once_for_dynamic_offer_copy():
    page = MagicMock(url=URL)
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.locator.return_value.wait_for = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.content = AsyncMock(side_effect=[
        f"<main><h1>This site requires JavaScript</h1><p>{JAVASCRIPT_SHELL}</p></main>",
        f"<main><p>{COPY}</p></main>",
    ])
    page.title = AsyncMock(return_value="Guide")
    context = MagicMock(new_page=AsyncMock(return_value=page))
    browser = MagicMock(new_context=AsyncMock(return_value=context), close=AsyncMock())
    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    manager = MagicMock(__aenter__=AsyncMock(return_value=playwright),
                        __aexit__=AsyncMock())
    with patch.object(scraper, "async_playwright", return_value=manager):
        result = asyncio.run(scraper._scrape_page(URL))
    page.wait_for_function.assert_awaited_once()
    assert result["main_content"] == COPY
    assert result["extraction_method"] == "browser"


def test_browser_javascript_shell_remains_explicit_extraction_error():
    page = MagicMock(url=URL)
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.locator.return_value.wait_for = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock()
    page.wait_for_function = AsyncMock(side_effect=scraper.PlaywrightTimeoutError(
        "dynamic content did not load"))
    page.content = AsyncMock(return_value=f"<main><p>{JAVASCRIPT_SHELL}</p></main>")
    page.title = AsyncMock(return_value="Imersão Reset Total | Life Reset")
    context = MagicMock(new_page=AsyncMock(return_value=page))
    browser = MagicMock(new_context=AsyncMock(return_value=context), close=AsyncMock())
    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    manager = MagicMock(__aenter__=AsyncMock(return_value=playwright),
                        __aexit__=AsyncMock())
    with patch.object(scraper, "async_playwright", return_value=manager):
        result = asyncio.run(scraper._scrape_page(URL))
    assert result["error"]
    assert result["extraction_method"] == "browser"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows event loop compatibility")
def test_windows_selector_loop_uses_separate_proactor_loop():
    loops = []

    async def fake_scrape(url):
        loops.append(asyncio.get_running_loop())
        return dict(SOURCE)

    with patch.object(scraper, "_scrape_page", new=fake_scrape):
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            result = runner.run(scraper.scrape_landing_page(URL))
    assert result["main_content"] == COPY
    assert isinstance(loops[0], asyncio.ProactorEventLoop)


@pytest.mark.parametrize("status,timeout", [(404, False), (200, True), (200, False)])
def test_async_scraper_closes_browser_on_failure_and_success(status, timeout):
    page = MagicMock(url=URL)
    page.goto = AsyncMock(side_effect=TimeoutError("navigation timeout") if timeout else None,
                          return_value=MagicMock(status=status))
    page.locator.return_value.wait_for = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock()
    page.content = AsyncMock(return_value=f"<main><p>{COPY}</p></main>")
    page.title = AsyncMock(return_value="Guide")
    context = MagicMock(new_page=AsyncMock(return_value=page))
    browser = MagicMock(new_context=AsyncMock(return_value=context), close=AsyncMock())
    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    manager = MagicMock(__aenter__=AsyncMock(return_value=playwright), __aexit__=AsyncMock())
    with patch.object(scraper, "async_playwright", return_value=manager):
        result = asyncio.run(scraper.scrape_landing_page(URL))
    browser.close.assert_awaited_once()
    assert ("error" in result) == (status == 404 or timeout)
    if status == 200 and not timeout:
        assert COPY in result["main_content"]


def test_browser_403_uses_validated_http_fallback():
    page = MagicMock(url=URL)
    page.goto = AsyncMock(return_value=MagicMock(status=403))
    context = MagicMock(new_page=AsyncMock(return_value=page))
    browser = MagicMock(new_context=AsyncMock(return_value=context), close=AsyncMock())
    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    manager = MagicMock(__aenter__=AsyncMock(return_value=playwright), __aexit__=AsyncMock())
    fallback = {**SOURCE, "http_status": 200, "extraction_method": "http_fallback"}
    with patch.object(scraper, "async_playwright", return_value=manager), \
            patch.object(scraper, "_scrape_page_http", new=AsyncMock(return_value=fallback)) as http:
        result = asyncio.run(scraper._scrape_page(URL))
    http.assert_awaited_once_with(URL)
    browser.close.assert_awaited_once()
    assert result == fallback


def test_markdown_url_and_ambiguous_urls():
    assert requested_url(types.Content(parts=[types.Part.from_text(text=f"[Landing]({URL})")])) == URL
    with pytest.raises(ValueError, match="única URL"):
        requested_url(types.Content(parts=[types.Part.from_text(text=URL + " https://other.example")]))


def test_prompt_document_matches_runtime_instruction():
    doc = Path(__file__).resolve().parents[1] / "prompt_landing_page_research_agent.md"
    assert doc.read_text(encoding="utf-8").split("-->\n\n", 1)[1].strip() == LANDING_PAGE_COPYWRITER_INSTRUCTION.strip()


def visual_analysis(file_index=1, pages=None):
    data = valid_analysis()
    data['attachment_pages'] = pages or [{'file_index': file_index, 'page': 1, 'text': COPY}]
    for item in data['evidence']:
        item.update(file_index=file_index, page=1)
    return json.dumps(data)


async def attachment_scenario(messages, outputs, source=None):
    model = StubModel(output=outputs)
    landing = GroundedLandingPageAgent(
        name='LandingPageResearcher', model=model, instruction=LANDING_PAGE_COPYWRITER_INSTRUCTION,
        output_key='landing_page_research', before_model_callback=current_source_only,
        include_contents='none')
    class Report(DownstreamAgent):
        async def _run_async_impl(self, ctx):
            self.calls += 1
            delta = {'market_research_report': 'Informe de prueba'}
            ctx.session.state.update(delta)
            yield Event(author=self.name, invocation_id=ctx.invocation_id,
                        actions=EventActions(state_delta=delta))
    downstream = [DownstreamAgent(name=f'next_{i}') for i in range(3)] + [Report(name='report')]
    root = GroundedCampaignOrchestrator(name='pipeline', sub_agents=[landing, *downstream])
    service = InMemorySessionService()
    await service.create_session(app_name='test', user_id='user', session_id='attachment')
    runner = Runner(agent=root, app_name='test', session_service=service)
    snapshots, turns = [], []
    with patch('marketing_campaign_agent.landing_research.scrape_landing_page',
               new=AsyncMock(return_value=source or {'error': 'HTTP 403', 'url': URL})) as scrape:
        for parts in messages:
            turns.append([event async for event in runner.run_async(
                user_id='user', session_id='attachment',
                new_message=types.Content(role='user', parts=parts))])
            state = (await service.get_session(
                app_name='test', user_id='user', session_id='attachment')).state
            snapshots.append(json.loads(json.dumps(state)))
    return snapshots, turns, model, downstream, scrape


@pytest.mark.parametrize('mime', ['application/pdf', 'image/png', 'image/jpeg', 'image/webp'])
def test_attachment_continues_same_session_without_navigation_or_resume(mime):
    media = types.Part.from_bytes(data=b'fixture media', mime_type=mime)
    states, _, model, downstream, scrape = asyncio.run(attachment_scenario(
        [[types.Part.from_text(text=URL)], [media]], visual_analysis()))
    assert states[0][STATUS_KEY]['status'] == WAITING_ATTACHMENT
    assert states[0]['market_research_report'] is None
    assert states[1][STATUS_KEY]['status'] == 'validated'
    assert states[1]['pipeline_run']['status'] == 'finished'
    assert all(stage.calls == 1 for stage in downstream)
    scrape.assert_awaited_once_with(URL)
    assert len(model.requests) == 1
    assert [p.inline_data.data for p in model.requests[0].contents[0].parts if p.inline_data] == [b'fixture media']
    result = json.loads(states[1]['landing_page_research'])
    assert result['source_info']['url_content_verified'] is False
    assert result['source_info']['requested_url'] == URL
    assert result['evidence'][0]['page'] == 1
    assert states[1]['landing_page_source']['transcription_method'] == 'gemini_visual'
    assert 'archivo 1' in states[1]['market_research_report']
    assert 'no se verificó el contenido actual de la URL' in states[1]['market_research_report']


def test_waiting_without_file_does_not_restart_scraper_or_model():
    states, _, model, downstream, scrape = asyncio.run(attachment_scenario(
        [[types.Part.from_text(text=URL)], [types.Part.from_text(text='continúa')]], visual_analysis()))
    assert states[-1][STATUS_KEY]['status'] == WAITING_ATTACHMENT
    assert not model.requests and not any(stage.calls for stage in downstream)
    scrape.assert_awaited_once()


def test_incomplete_attachment_can_be_supplemented_in_same_session():
    first = types.Part.from_bytes(data=b'first image', mime_type='image/png')
    second = types.Part.from_bytes(data=b'second image', mime_type='image/jpeg')
    pages = [{'file_index': 1, 'page': 1, 'text': 'Original fragment'},
             {'file_index': 2, 'page': 1, 'text': COPY}]
    states, _, model, downstream, scrape = asyncio.run(attachment_scenario(
        [[types.Part.from_text(text=URL)], [first], [second]],
        [json.dumps({'error': 'Falta la sección de entregables.'}), visual_analysis(2, pages)]))
    assert states[1][STATUS_KEY]['status'] == WAITING_ATTACHMENT
    assert 'entregables' in states[1][STATUS_KEY]['error']
    assert states[1]['landing_page_research'] is None
    assert states[2][STATUS_KEY]['status'] == 'validated'
    assert len(states[2]['landing_page_source']['attachments']) == 2
    sent = [p.inline_data.data for p in model.requests[-1].contents[0].parts if p.inline_data]
    assert sent == [b'first image', b'second image']
    assert all(stage.calls == 1 for stage in downstream)
    scrape.assert_awaited_once()


@pytest.mark.parametrize('output', ['not json', '{"error":"Texto ilegible"}',
                                  visual_analysis(file_index=9)])
def test_invalid_visual_response_requests_attachment_without_downstream(output):
    states, _, _, downstream, _ = asyncio.run(attachment_scenario(
        [[types.Part.from_text(text=URL)],
         [types.Part.from_bytes(data=b'pdf fixture', mime_type='application/pdf')]], output))
    assert states[-1][STATUS_KEY]['status'] == WAITING_ATTACHMENT
    assert states[-1]['market_research_report'] is None
    assert states[-1]['landing_page_research'] is None
    assert not any(stage.calls for stage in downstream)


def test_page_reference_must_contain_the_actual_quote():
    output = json.loads(visual_analysis())
    output['evidence'][0]['page'] = 2
    states, _, _, downstream, _ = asyncio.run(attachment_scenario(
        [[types.Part.from_text(text=URL)],
         [types.Part.from_bytes(data=b'pdf fixture', mime_type='application/pdf')]], json.dumps(output)))
    assert states[-1][STATUS_KEY]['status'] == 'error'
    assert 'No se pudo corregir automáticamente' in states[-1][STATUS_KEY]['error']
    assert 'no requiere otro archivo' in states[-1][STATUS_KEY]['error']
    assert not any(stage.calls for stage in downstream)


def test_new_url_does_not_reuse_pending_attachments():
    other = 'https://other.example/landing'
    states, _, model, downstream, scrape = asyncio.run(attachment_scenario(
        [[types.Part.from_text(text=URL)],
         [types.Part.from_bytes(data=b'previous file', mime_type='image/png')],
         [types.Part.from_text(text=other)]], '{"error":"Falta la promesa"}'))
    assert states[-1][STATUS_KEY]['url'] == other
    assert states[-1]['landing_page_source'] is None
    assert scrape.await_count == 2
    assert len(model.requests) == 1
    assert not any(stage.calls for stage in downstream)


def test_unsupported_attachment_never_reaches_model():
    states, _, model, _, _ = asyncio.run(attachment_scenario(
        [[types.Part.from_text(text=URL)],
         [types.Part.from_bytes(data=b'audio', mime_type='audio/mp3')]], visual_analysis()))
    assert states[-1][STATUS_KEY]['status'] == WAITING_ATTACHMENT
    assert not model.requests


def test_visual_ambiguous_queries_repair_only_rejected_indices_without_rereading_pdf():
    draft = json.loads(visual_analysis())
    draft['youtube_keywords'][0] = 'cómo controlar la adicción al pan y los dulces con la fe'
    draft['youtube_keywords'][1] = 'cómo romper el ciclo de engordar y adelgazar definitivamente'
    repaired = valid_analysis()
    # Even if the model changes accepted queries and the offer, Python ignores those changes.
    repaired['youtube_keywords'][2] = 'cambio no autorizado'
    repaired['offer']['description'] = 'OTRA OFERTA'
    states, turns, model, downstream, scrape = asyncio.run(attachment_scenario(
        [[types.Part.from_text(text=URL)],
         [types.Part.from_bytes(data=b'pdf fixture', mime_type='application/pdf')]],
        [json.dumps(draft), json.dumps(repaired)]))
    state = states[-1]
    assert state[STATUS_KEY]['status'] == 'validated'
    assert len(model.requests) == 2
    assert all(stage.calls == 1 for stage in downstream)
    scrape.assert_awaited_once()
    request = model.requests[1]
    assert not any(p.inline_data for c in request.contents for p in c.parts)
    assert 'attachment_pages' not in request.contents[0].parts[0].text
    assert 'CORRECCIÓN OBLIGATORIA' in request.contents[0].parts[0].text
    result = json.loads(state['landing_page_research'])
    assert result['youtube_keywords'] == valid_analysis()['youtube_keywords']
    assert result['offer'] == draft['offer']
    assert result['deseos'] == draft['deseos'] and result['problemas'] == draft['problemas']
    assert state['landing_page_source']['main_content'] == COPY
    events = turns[-1]
    saved = next(i for i, e in enumerate(events)
                 if (e.actions.state_delta.get('landing_page_source') or {}).get('main_content') == COPY)
    repairing = next(i for i, e in enumerate(events)
                     if (e.actions.state_delta.get(STATUS_KEY) or {}).get('status') == 'repairing_keywords')
    assert saved < repairing
    assert not any('Adjunta aquí' in (p.text or '') for e in events if e.content for p in e.content.parts)


@pytest.mark.parametrize('reply', ['not json', '{"youtube_keywords":[]}', None])
def test_failed_query_repair_keeps_transcription_without_requesting_another_pdf(reply):
    draft = json.loads(visual_analysis())
    draft['youtube_keywords'][0] = 'cómo romper el ciclo de engordar y adelgazar definitivamente'
    states, turns, model, downstream, _ = asyncio.run(attachment_scenario(
        [[types.Part.from_text(text=URL)],
         [types.Part.from_bytes(data=b'pdf fixture', mime_type='application/pdf')]],
        [json.dumps(draft), reply if reply is not None else json.dumps(draft)]))
    assert len(model.requests) == 2
    assert states[-1][STATUS_KEY]['status'] == 'error'
    assert states[-1]['landing_page_source']['main_content'] == COPY
    assert states[-1]['landing_page_research'] is None
    assert not any(stage.calls for stage in downstream)
    messages = [p.text for e in turns[-1] if e.content for p in e.content.parts if p.text]
    assert not any('Adjunta aquí' in message for message in messages)
    assert any('no requiere otro archivo' in message for message in messages)


def test_continue_retries_failed_repair_from_saved_pdf_without_reupload():
    draft = json.loads(visual_analysis())
    draft['youtube_keywords'][0] = 'curso de harmonização com preenchimento'
    states, _, model, downstream, scrape = asyncio.run(attachment_scenario(
        [[types.Part.from_text(text=URL)],
         [types.Part.from_bytes(data=b'pdf fixture', mime_type='application/pdf')],
         [types.Part.from_text(text='continúa')]],
        [json.dumps(draft), 'not json', visual_analysis()]))
    assert states[1][STATUS_KEY]['status'] == 'error'
    assert states[1][STATUS_KEY]['error_code'] == 'bounded_repair_failed'
    assert states[1][STATUS_KEY]['next_action'] == 'retry_saved_source'
    assert states[2][STATUS_KEY]['status'] == 'validated'
    assert len(model.requests) == 3
    assert all(agent.calls == 1 for agent in downstream)
    scrape.assert_awaited_once_with(URL)


def test_query_repair_cannot_bypass_invalid_visual_evidence():
    draft = json.loads(visual_analysis())
    draft['youtube_keywords'][0] = 'cómo mejorar resultados'
    draft['evidence'][0]['quote'] = 'Esta cita no existe en ninguna página del PDF.'
    states, _, model, downstream, _ = asyncio.run(attachment_scenario(
        [[types.Part.from_text(text=URL)],
         [types.Part.from_bytes(data=b'pdf fixture', mime_type='application/pdf')]], json.dumps(draft)))
    assert len(model.requests) == 2
    assert '"repair_type": "evidence"' in model.requests[1].contents[0].parts[0].text
    assert states[-1]['landing_page_research'] is None
    assert not any(stage.calls for stage in downstream)


def test_invalid_quote_is_repaired_once_without_changing_analysis():
    draft = valid_analysis()
    target = next(item for item in draft['evidence'] if item['field'] == 'deseos.2')
    target['quote'] = 'A translated or paraphrased quote that is not in the landing'
    repaired = {
        'evidence': [{
            'field': 'deseos.2', 'quote': COPY, 'kind': target['kind'],
        }],
        'deseos': ['CAMBIO NO AUTORIZADO'],
    }
    session, events, model, downstream, _ = asyncio.run(run_pipeline(
        SOURCE, [json.dumps(draft), json.dumps(repaired)]))
    assert len(model.requests) == 2
    assert session.state[STATUS_KEY]['status'] == 'validated'
    result = json.loads(session.state['landing_page_research'])
    assert result['deseos'] == draft['deseos']
    assert result['offer'] == draft['offer']
    repaired_entry = next(item for item in result['evidence'] if item['field'] == 'deseos.2')
    assert repaired_entry['quote'] == COPY
    assert all(stage.calls == 1 for stage in downstream)
    messages = [part.text for event in events if event.content
                for part in event.content.parts or [] if part.text]
    assert any('Corrigiendo automáticamente 1 cita' in message for message in messages)


@pytest.mark.parametrize('resolved', [True, False])
def test_cloudflare_wait_is_bounded_and_does_not_accept_challenge(resolved):
    blocked = MagicMock(status=403, headers={'cf-mitigated': 'challenge'})
    success = MagicMock(status=200)
    page = MagicMock(url=URL)
    success.frame = page.main_frame
    success.request.is_navigation_request.return_value = True
    page.goto = AsyncMock(return_value=blocked)
    page.locator.return_value.wait_for = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock()
    page.content = AsyncMock(return_value=f'<main>{COPY}</main>')
    page.title = AsyncMock(return_value='Guide')

    async def finish_challenge(*args, **kwargs):
        assert kwargs['timeout'] == 10000
        if not resolved:
            raise scraper.PlaywrightTimeoutError('challenge remains')
        page.on.call_args.args[1](success)

    page.wait_for_function = AsyncMock(side_effect=finish_challenge)
    context = MagicMock(new_page=AsyncMock(return_value=page))
    browser = MagicMock(new_context=AsyncMock(return_value=context), close=AsyncMock())
    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    manager = MagicMock(__aenter__=AsyncMock(return_value=playwright), __aexit__=AsyncMock())
    with patch.object(scraper, 'async_playwright', return_value=manager), \
            patch.object(scraper, '_scrape_page_http', new=AsyncMock(return_value={'error': 'HTTP 403'})) as http:
        result = asyncio.run(scraper._scrape_page(URL))
    browser.close.assert_awaited_once()
    if resolved:
        assert result['http_status'] == 200 and COPY in result['main_content']
        http.assert_not_awaited()
    else:
        assert result['error'] == 'HTTP 403'
        http.assert_awaited_once_with(URL)
