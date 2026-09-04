"""Regression tests: use the real async ADK Runner without external API calls."""

import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.adk.agents import BaseAgent
from google.adk.events import Event
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
    current_source_only, requested_url, validate_research,
)
from marketing_campaign_agent.tools import landing_page_scraper as scraper


URL = "https://www.musicofwisdom.com/100frequencies"
COPY = (
    "Download the 100 Frequencies for Healing PDF Guide. "
    "Get 8 days of email tutorials and free music to apply the frequencies in daily life. "
    "Explore relaxation, focus, creativity, deep sleep and emotional balance."
)
SOURCE = {
    "url": URL, "requested_url": URL, "title": "100 Frequencies for Healing",
    "suggested_page_type": "TSL", "page_language": "en", "main_content": COPY,
}


def valid_analysis():
    fields = ["offer.description", "offer.deliverables.0", "main_promise", "avatar"]
    fields += [f"{key}.{i}" for key, n in (("deseos", 3), ("problemas", 3),
                                         ("youtube_keywords", 5)) for i in range(n)]
    return {
        "offer": {"description": "Guía PDF y tutoriales", "deliverables": ["Guía PDF"]},
        "avatar": {"name": "Personas interesadas en frecuencias", "description": "Buscan bienestar",
                   "demographics": {"age_range": None, "gender": None, "language": None}},
        "main_promise": "Aprender a aplicar frecuencias en la vida diaria",
        "deseos": ["Relajación", "Concentración", "Descanso"],
        "problemas": ["Estrés", "Distracción", "Dificultad para descansar"],
        "youtube_keywords": ["frecuencias relajación", "frecuencias concentración",
                             "frecuencias descanso", "aplicar frecuencias", "frecuencias bienestar"],
        "evidence": [{"field": f, "quote": COPY,
                      "kind": "explicit" if f.startswith("offer.") or f == "main_promise"
                      else "inference"} for f in fields],
    }


class StubModel(BaseLlm):
    model: str = "offline-test"
    output: str
    requests: list = Field(default_factory=list)
    partial_text: str | None = None

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request)
        if self.partial_text:
            yield LlmResponse(partial=True, content=types.Content(role="model", parts=[
                types.Part.from_text(text=self.partial_text)]))
        yield LlmResponse(content=types.Content(role="model", parts=[
            types.Part.from_text(text=self.output)]))


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
    assert session.state[STATUS_KEY]["status"] == "error"
    assert "Investigación detenida" in events[-1].content.parts[0].text


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


@pytest.mark.parametrize("bad_output", ["not json", '{"error": "No evidence"}',
                                         '{"main_promise": "Commercial licensing"}'])
def test_invalid_model_output_is_never_published_or_used(bad_output):
    session, events, model, downstream, _ = asyncio.run(run_pipeline(
        SOURCE, output=bad_output, partial_text="UNVERIFIED_STREAM"))
    assert len(model.requests) == 1
    assert all(a.calls == 0 for a in downstream)
    assert session.state["landing_page_research"] is None
    assert session.state[STATUS_KEY]["status"] == "error"
    assert not any("UNVERIFIED_STREAM" in (p.text or "")
                   for e in events if e.content for p in e.content.parts or [])


def test_fabricated_quote_and_missing_evidence_are_rejected():
    data = valid_analysis()
    data["evidence"][0]["quote"] = "Unlimited royalty-free commercial licensing"
    with pytest.raises(ValueError, match="no existe"):
        validate_research(json.dumps(data), SOURCE)
    data = valid_analysis()
    data["evidence"].pop()
    with pytest.raises(ValueError, match="Falta evidencia"):
        validate_research(json.dumps(data), SOURCE)


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


def test_markdown_url_and_ambiguous_urls():
    assert requested_url(types.Content(parts=[types.Part.from_text(text=f"[Landing]({URL})")])) == URL
    with pytest.raises(ValueError, match="única URL"):
        requested_url(types.Content(parts=[types.Part.from_text(text=URL + " https://other.example")]))


def test_prompt_document_matches_runtime_instruction():
    doc = Path(__file__).resolve().parents[1] / "prompt_landing_page_research_agent.md"
    assert doc.read_text(encoding="utf-8").split("-->\n\n", 1)[1].strip() == LANDING_PAGE_COPYWRITER_INSTRUCTION.strip()
