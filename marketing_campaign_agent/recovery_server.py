"""ADK web launcher with startup recovery of interrupted comment pipelines.

Run from the project root: python -m marketing_campaign_agent.recovery_server
"""
import asyncio
from contextlib import asynccontextmanager, suppress
import json
import logging
import os
from pathlib import Path
import sqlite3

import httpx
import uvicorn
from google.adk.cli.fast_api import get_fast_api_app

from . import recovery_runtime

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent


def eligible_for_restart(state):
    run = state.get('pipeline_run') or {}
    return (run.get('status') == 'active' and run.get('stage', -1) >= 2
            and bool(state.get('youtube_comments_collected')))


def interrupted_sessions():
    path = ROOT / '.adk' / 'session.db'
    if not path.exists():
        return []
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        records = db.execute('select app_name,user_id,id,state from sessions').fetchall()
    pending = []
    for app, user, sid, raw in records:
        state = json.loads(raw)
        if eligible_for_restart(state):
            pending.append((app, user, sid))
    return pending


async def recover_on_startup(base_url):
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        for _ in range(30):
            try:
                response = await client.get(base_url + '/list-apps')
                response.raise_for_status()
                break
            except (httpx.HTTPError, OSError):
                await asyncio.sleep(1)
        else:
            LOG.error('No se pudo iniciar la recuperación: ADK no responde')
            return
        for app, user, sid in await asyncio.to_thread(interrupted_sessions):
            # The orchestrator acquires the cross-process lock and rechecks
            # cancellation/attempt limits using the freshly loaded session.
            try:
                async with client.stream('POST', base_url + '/run_sse', timeout=None, json={
                    'app_name': app, 'user_id': user, 'session_id': sid,
                    'new_message': {'role': 'user', 'parts': [{'text': recovery_runtime.AUTO_RESUME}]},
                    'streaming': False,
                }) as response:
                    response.raise_for_status()
                    async for _ in response.aiter_lines():
                        pass
            except httpx.HTTPError:
                LOG.exception('No se pudo recuperar la sesión %s', sid)


def create_app(port=8000):
    @asynccontextmanager
    async def lifespan(app):
        recovery_runtime.SHUTTING_DOWN = False
        task = asyncio.create_task(recover_on_startup(f'http://127.0.0.1:{port}'))
        try:
            yield
        finally:
            recovery_runtime.SHUTTING_DOWN = True
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return get_fast_api_app(agents_dir=str(ROOT.parent), web=True, port=port,
                            reload_agents=False, lifespan=lifespan)


class RecoveryServer(uvicorn.Server):
    def handle_exit(self, sig, frame):
        # Mark server shutdown before Uvicorn cancels active requests, so it
        # cannot be mistaken for a user cancelling a single execution.
        recovery_runtime.SHUTTING_DOWN = True
        super().handle_exit(sig, frame)


if __name__ == '__main__':
    port = int(os.getenv('PORT', '8000'))
    RecoveryServer(uvicorn.Config(create_app(port), host='127.0.0.1', port=port,
                                  timeout_graceful_shutdown=5)).run()
