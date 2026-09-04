"""Run only landing research through ADK; save evidence without starting YouTube.

Usage (from the repository root):
    .venv/Scripts/python marketing_campaign_agent/diagnostics/verify_landing.py URL
"""

import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from marketing_campaign_agent.agent import landing_page_research_agent


async def main(url):
    service = InMemorySessionService()
    agent = landing_page_research_agent.clone()
    runner = Runner(agent=agent, app_name="landing_diagnostic", session_service=service)
    await service.create_session(app_name="landing_diagnostic", user_id="local", session_id="fresh")
    async for event in runner.run_async(
        user_id="local", session_id="fresh",
        new_message=types.Content(role="user", parts=[types.Part.from_text(text=url)]),
    ):
        phase = event.actions.state_delta.get("landing_page_research_status")
        if phase:
            print("PHASE", json.dumps(phase, ensure_ascii=True), flush=True)
    session = await service.get_session(app_name="landing_diagnostic", user_id="local", session_id="fresh")
    output = Path(__file__).resolve().parent
    for key, name in (("landing_page_source", "landing_source.json"),
                      ("landing_page_research", "landing_analysis.json"),
                      ("landing_page_research_status", "landing_status.json")):
        value = session.state.get(key)
        if isinstance(value, str):
            value = json.loads(value)
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    status = session.state.get("landing_page_research_status", {})
    print("MODEL", str(agent.model))
    print("RESULT", status.get("status"))
    if status.get("status") != "validated":
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
