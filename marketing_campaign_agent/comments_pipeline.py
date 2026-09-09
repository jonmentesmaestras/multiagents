"""Deterministic orchestration for comment collection."""

import asyncio
import hashlib
import json
import os
import re
import time
import unicodedata
from email.utils import parsedate_to_datetime
from copy import deepcopy
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.events import Event, EventActions
from google.genai import types

from .tools.youtube_comment_extractor_tool import extract_comments_from_videos
from .tools.youtube_api_tool import extract_video_id, search_and_collect_youtube_data

CLASSIFICATION_BATCH_SIZE = max(1, int(os.getenv("COMMENTS_BATCH_SIZE", "25")))
CLASSIFICATION_CONCURRENCY = max(1, int(os.getenv("COMMENTS_CONCURRENCY", "1")))
CLASSIFICATION_TARGET = max(1, int(os.getenv("COMMENTS_TARGET", "100")))
RECOVERY_ROUNDS = 3
RECOVERY_SECONDS = max(1, int(os.getenv("COMMENTS_RECOVERY_SECONDS", "600")))
RATE_LIMIT_BACKOFF_SECONDS = max(1, int(os.getenv("COMMENTS_RATE_LIMIT_BACKOFF_SECONDS", "60")))
VIDEO_VALIDATION_BATCH_SIZE = 10
VIDEO_VALIDATION_ATTEMPTS = 3
DETERMINISTIC_GENERATION_SEED = 17

_GENERIC_VIDEO_WORDS = {
    "artificial", "chatgpt", "como", "con", "crear", "curso", "de", "del",
    "desde", "el", "en", "enseña", "este", "hacer", "ia", "inteligencia",
    "la", "las", "lo", "los", "mejor", "para", "prompt", "prompts", "secreto",
    "todos", "tutorial", "usar", "video", "videos", "y",
}


def _market_signal_counts(results):
    desires = sum(item.get("decision") == "deseo" for item in results)
    problems = sum(item.get("decision") == "problema" for item in results)
    return desires, problems


def _market_signal_reached_counts(desires, problems, total_target=None):
    if total_target is None:
        total_target = CLASSIFICATION_TARGET
    return desires > 50 or problems > 50 or desires + problems >= total_target


def _market_signal_reached(results):
    """Apply the three independent stop conditions from the user prompt."""
    desires, problems = _market_signal_counts(results)
    return _market_signal_reached_counts(desires, problems)


def technical_pending(item):
    return item.get('decision') == 'requiere_revision' and (
        item.get('failure_kind') == 'technical_error' or
        str(item.get('reason', '')).startswith('Lote no validado tras'))


def failure_details(exc):
    code = getattr(exc, 'code', None) or getattr(exc, 'status_code', None)
    permanent = str(code) in {'400', '401', '403', '404'}
    response = getattr(exc, 'response', None)
    headers = getattr(response, 'headers', {}) or {}
    try:
        delay = max(0, float(headers.get('retry-after', 0)))
    except (ValueError, TypeError):
        try:
            delay = max(0, parsedate_to_datetime(headers.get('retry-after', '')).timestamp() - time.time())
        except (ValueError, TypeError, AttributeError):
            delay = 0
    rate_limited = str(code) == '429'
    if rate_limited and not delay:
        delay = RATE_LIMIT_BACKOFF_SECONDS
    return {'error_type': type(exc).__name__, 'error_code': code,
            'message': str(exc)[:500], 'permanent': permanent,
            'rate_limited': rate_limited, 'retry_after': delay,
            'transient': str(code) in {'429', '500', '502', '503', '504'}
            or isinstance(exc, (TimeoutError, ConnectionError))}


def generate_response(client, **kwargs):
    try:
        return client.models.generate_content(**kwargs)
    except StopIteration as exc:
        raise RuntimeError('El proveedor terminó sin respuesta') from exc


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(text, strict=False)
    return value


def _problems(videos):
    return [v for v in videos if v.get("collection_status") not in {"complete", "excluded_by_rule"}]


def _consolidate_videos(videos):
    """Merge repeated video entries and comment threads by their stable IDs."""
    merged = {}
    duplicate_videos = 0
    duplicate_comments = 0
    comments_without_id = 0
    conflicts = []
    for video in videos:
        href = video.get("video_href", "")
        is_new_video = href not in merged
        if not is_new_video:
            duplicate_videos += 1
            target = merged[href]
            if target.get("collection_status") != "complete" and video.get("collection_status") == "complete":
                target["collection_status"] = "complete"
                target["collection_error"] = None
        else:
            target = deepcopy(video)
            target["3_months_comments"] = []
            target["source_occurrences"] = 1
            merged[href] = target
        if not is_new_video:
            target["source_occurrences"] = target.get("source_occurrences", 1) + 1
        by_id = {str(item.get("comment_id")): item for item in target["3_months_comments"] if item.get("comment_id")}
        for comment in video.get("3_months_comments", []):
            comment_id = comment.get("comment_id")
            if not comment_id:
                comments_without_id += 1
                target["3_months_comments"].append(deepcopy(comment))
                continue
            key = str(comment_id)
            if key in by_id:
                duplicate_comments += 1
                existing = by_id[key]
                if existing.get("Msg", "") != comment.get("Msg", ""):
                    conflicts.append(key)
                continue
            copy = deepcopy(comment)
            target["3_months_comments"].append(copy)
            by_id[key] = copy
    result = list(merged.values())
    for video in result:
        video["3_months_comments"].sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return result, {"duplicate_videos": duplicate_videos, "duplicate_comments": duplicate_comments,
                    "comments_without_id": comments_without_id, "text_conflicts": sorted(set(conflicts))}


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def report_metrics_context(callback_context, llm_request):
    """Give the report verified counts without copying the whole dataset again."""
    metrics = callback_context.state.get("market_research_metrics")
    if not metrics or metrics.get("coverage", {}).get("status") != "verified":
        raise ValueError("El informe requiere métricas calculadas con cobertura verificada")
    payload = {"landing_page_research": _decode(callback_context.state.get("landing_page_research")),
               "metrics": metrics}
    llm_request.contents = [types.Content(role="user", parts=[types.Part.from_text(
        text="Redacta el informe en español usando estas métricas verificadas por Python. "
             "Conserva exactamente los conteos y la decisión suministrados. No necesitas volver a "
             "llamar las herramientas de conteo: ya fueron ejecutadas sobre el conjunto completo.\n"
             + json.dumps(payload, ensure_ascii=False))])]


def _validate_batch(candidate, batch, categories):
    if not isinstance(candidate, list) or not all(isinstance(x, dict) for x in candidate):
        raise ValueError("La respuesta no es una lista de decisiones")
    expected = {str(x["comment_id"]) for x in batch}
    ids = [str(x.get("comment_id", "")) for x in candidate]
    if set(ids) != expected or len(ids) != len(batch) or len(ids) != len(set(ids)):
        raise ValueError("Comentarios faltantes, repetidos o con identificadores desconocidos")
    for item in candidate:
        decision, category = item.get("decision"), item.get("category_id")
        if decision not in {"deseo", "problema", "no_aplica", "requiere_revision"}:
            raise ValueError("Decisión no válida")
        if decision in {"deseo", "problema"}:
            if category not in categories or not category.startswith("D" if decision == "deseo" else "P"):
                raise ValueError("Categoría incompatible con la decisión")
        elif category is not None:
            raise ValueError("Una decisión sin clasificación no debe tener categoría")
    return candidate


def _semantic_tokens(value):
    text = unicodedata.normalize("NFKD", str(value).lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    tokens = []
    for token in re.findall(r"[a-z0-9]+", text):
        if len(token) < 3 or token in _GENERIC_VIDEO_WORDS:
            continue
        if len(token) > 5 and token.endswith("es"):
            token = token[:-2]
        elif len(token) > 4 and token.endswith("s"):
            token = token[:-1]
        tokens.append(token)
    return set(tokens)


def _normalize_for_evidence(value):
    text = unicodedata.normalize("NFKD", str(value).lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _landing_anchor_tokens(landing_context):
    return _semantic_tokens(json.dumps(landing_context, ensure_ascii=False))


def _validate_video_batch(candidate, batch, landing_context):
    """Require one grounded decision for every candidate in a validation batch."""
    if not isinstance(candidate, list) or not all(isinstance(item, dict) for item in candidate):
        raise ValueError("La respuesta no es una lista de decisiones de video")
    expected = {str(item["video_id"]) for item in batch}
    ids = [str(item.get("video_id", "")) for item in candidate]
    if set(ids) != expected or len(ids) != len(batch) or len(ids) != len(set(ids)):
        raise ValueError("Videos faltantes, repetidos o con identificadores desconocidos")
    by_id = {str(item["video_id"]): item for item in batch}
    landing_anchors = _landing_anchor_tokens(landing_context)
    for item in candidate:
        source = by_id[str(item["video_id"])]
        if item.get("decision") not in {"accepted", "rejected"}:
            raise ValueError("Decisión de video no válida")
        if not str(item.get("language", "")).strip():
            raise ValueError("Cada video requiere idioma")
        if (item.get("decision") == "accepted"
                and not str(item.get("language", "")).strip().lower().startswith("es")):
            item["decision"] = "rejected"
            item["reason"] = "El video no está identificado en español."
        if not str(item.get("reason", "")).strip():
            raise ValueError("Cada video requiere una razón")
        if not str(item.get("evidence", "")).strip():
            item["evidence"] = (str(source.get("video_title") or "").strip()
                                or str(source.get("video_description") or "").strip())
            if item.get("decision") == "accepted":
                item["decision"] = "rejected"
                item["reason"] = (
                    "El modelo no proporcionó evidencia literal para aceptar el video."
                )
                item["selection_reason"] = "missing_relevance_evidence"
        if item.get("decision") == "accepted":
            metadata = "\n".join((str(source.get("video_title") or ""),
                                    str(source.get("video_description") or "")))
            evidence = str(item["evidence"]).strip()
            if _normalize_for_evidence(evidence) not in _normalize_for_evidence(metadata):
                item["decision"] = "rejected"
                item["reason"] = "La evidencia indicada no aparece en el título ni en la descripción."
                item["selection_reason"] = "ungrounded_relevance_evidence"
            elif not (_semantic_tokens(evidence) & landing_anchors):
                item["decision"] = "rejected"
                item["reason"] = (
                    "El título o la descripción solo sustentan un mecanismo genérico y no contienen "
                    "contexto específico de la landing."
                )
                item["selection_reason"] = "insufficient_landing_context"
    return candidate


class BatchedVideoAnalyzerAgent(LlmAgent):
    """Search each query independently and validate candidates in bounded batches."""

    async def _run_async_impl(self, ctx):
        def emit(delta, text=None):
            ctx.session.state.update(delta)
            return Event(author=self.name, invocation_id=ctx.invocation_id,
                         branch=ctx.branch, actions=EventActions(state_delta=delta),
                         content=types.Content(role="model", parts=[types.Part.from_text(text=text)])
                         if text else None)

        candidates_by_id = {}
        decisions = []
        ledger = {}
        client = None
        try:
            landing = _decode(ctx.session.state.get("landing_page_research")) or {}
            queries = [str(value).strip() for value in landing.get("youtube_keywords", [])
                       if str(value).strip()]
            if not queries:
                raise ValueError("La landing validada no contiene consultas de YouTube")
            yield emit({"youtube_videos_research": None, "youtube_search_status": {
                "status": "searching", "query_count": len(queries), "queries": {},
                "candidate_count": 0, "candidates_decided": 0,
                "max_candidates_per_query": 50,
                "validation_batch_size": VIDEO_VALIDATION_BATCH_SIZE,
                "min_views": 0,
            }}, f"Búsqueda iniciada: {len(queries)} consultas, hasta 50 candidatos por consulta.")

            for position, query in enumerate(queries, 1):
                ledger[query] = {"status": "searching", "requested": 50,
                                 "found": 0, "accepted": 0, "rejected": 0,
                                 "requires_review": 0, "exhausted": False,
                                 "error": None}
                yield emit({"youtube_search_status": {
                    "status": "searching", "query_count": len(queries),
                    "current_query": position, "queries": deepcopy(ledger),
                    "candidate_count": len(candidates_by_id), "candidates_decided": 0,
                    "max_candidates_per_query": 50,
                    "validation_batch_size": VIDEO_VALIDATION_BATCH_SIZE, "min_views": 0,
                }}, f"Buscando consulta {position}/{len(queries)}: {query}")
                try:
                    rows = await asyncio.to_thread(
                        search_and_collect_youtube_data, query,
                        min_views=0, max_results_per_keyword=50)
                    if not isinstance(rows, list):
                        raise ValueError("La herramienta de YouTube no devolvió una lista")
                    ledger[query].update(status="complete", found=len(rows),
                                         exhausted=len(rows) < 50)
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        video_id = extract_video_id(str(row.get("video_href", "")))
                        if not video_id:
                            continue
                        if video_id not in candidates_by_id:
                            item = dict(row)
                            item["video_id"] = video_id
                            item["found_by_queries"] = []
                            candidates_by_id[video_id] = item
                        queries_for_video = candidates_by_id[video_id]["found_by_queries"]
                        if query not in queries_for_video:
                            queries_for_video.append(query)
                except Exception as exc:
                    ledger[query].update(status="error", error=f"{type(exc).__name__}: {exc}")
                yield emit({"youtube_search_status": {
                    "status": "searching", "query_count": len(queries),
                    "completed_queries": position, "queries": deepcopy(ledger),
                    "candidate_count": len(candidates_by_id), "candidates_decided": 0,
                    "max_candidates_per_query": 50,
                    "validation_batch_size": VIDEO_VALIDATION_BATCH_SIZE, "min_views": 0,
                }}, f"Consulta {position}/{len(queries)} registrada: "
                     f"{ledger[query]['found']} candidatos.")

            raw_candidates = list(candidates_by_id.values())
            for item in raw_candidates:
                item["video_keywords"] = "; ".join(item.pop("found_by_queries"))
            candidate_count = len(raw_candidates)
            eligible_candidates = []
            for item in raw_candidates:
                comment_count = item.get("comment_count")
                try:
                    comment_count = int(comment_count) if comment_count is not None else None
                except (ValueError, TypeError):
                    comment_count = None
                item["comment_count"] = comment_count
                if comment_count is None:
                    metadata_complete = item.get("metadata_status") == "complete"
                    decisions.append({**item,
                                      "detected_language": item.get("audio_language") or item.get("default_language") or "unknown",
                                      "relevance_decision": "rejected" if metadata_complete else "requires_review",
                                      "relevance_reason": (
                                          "El video no publica un conteo de comentarios utilizable."
                                          if metadata_complete else
                                          "No se pudo recuperar el total de comentarios del video."),
                                      "relevance_evidence": item.get("video_title", ""),
                                      "selection_reason": ("comments_unavailable" if metadata_complete
                                                           else "comment_count_unknown"),
                                      **({"validation_failure_kind": "technical_error"}
                                         if not metadata_complete else {})})
                elif comment_count <= 100:
                    decisions.append({**item,
                                      "detected_language": item.get("audio_language") or item.get("default_language") or "unknown",
                                      "relevance_decision": "rejected",
                                      "relevance_reason": "No supera el mínimo de 100 comentarios totales.",
                                      "relevance_evidence": item.get("video_title", ""),
                                      "selection_reason": "below_comment_threshold"})
                else:
                    eligible_candidates.append(item)
            eligible_candidates.sort(key=lambda item: (
                int(item.get("view_count") or 0) >= 25_000,
                int(item.get("comment_count") or 0),
                int(item.get("view_count") or 0),
                str(item.get("published_at") or "")), reverse=True)
            total_batches = ((len(eligible_candidates) + VIDEO_VALIDATION_BATCH_SIZE - 1)
                             // VIDEO_VALIDATION_BATCH_SIZE)
            if eligible_candidates:
                client = __import__("google.genai", fromlist=["Client"]).Client(
                    http_options=types.HttpOptions(
                        timeout=60000, retry_options=types.HttpRetryOptions(attempts=1)))

            landing_context = {
                "offer": landing.get("offer", {}),
                "main_promise": landing.get("main_promise", ""),
                "avatar": landing.get("avatar", {}),
                "deseos": landing.get("deseos", []),
                "problemas": landing.get("problemas", []),
            }
            for start in range(0, len(eligible_candidates), VIDEO_VALIDATION_BATCH_SIZE):
                batch = eligible_candidates[start:start + VIDEO_VALIDATION_BATCH_SIZE]
                batch_number = start // VIDEO_VALIDATION_BATCH_SIZE + 1
                prompt_rows = [{key: item.get(key) for key in (
                    "video_id", "video_title", "video_description", "channel_title",
                    "default_language", "audio_language", "video_keywords")}
                    for item in batch]
                prompt = (
                    "Valida semánticamente estos videos contra UNA sola landing. Devuelve exclusivamente "
                    "un arreglo JSON, una decisión por video_id. No agregues Markdown ni texto. "
                    "accepted puede ser direct (mecanismo de la oferta) o audience_context (un contexto de audiencia "
                    "que probablemente produzca comentarios sobre D1-D3 o P1-P3), siempre en español. "
                    "rejected incluye otro tema, otro idioma o metadatos insuficientes. "
                    "La consulta que encontró el video no es evidencia. Mencionar solo un mecanismo genérico, "
                    "como IA, prompts o ChatGPT, no demuestra relación con la landing. Para aceptar, el título "
                    "o la descripción debe nombrar también un producto, actividad, audiencia, deseo o problema "
                    "específico de la landing. Si la descripción está vacía y el título no establece esa conexión, "
                    "rechaza por metadatos insuficientes. Una coincidencia de palabras o popularidad no basta. "
                    "Campos obligatorios por fila: "
                    "video_id, decision (accepted|rejected), language (código es o es-*), reason, evidence (fragmento literal "
                    "del título o descripción que contiene el contexto específico, no la consulta de búsqueda).\n"
                    f"LANDING={json.dumps(landing_context, ensure_ascii=False)}\n"
                    f"VIDEOS={json.dumps(prompt_rows, ensure_ascii=False)}"
                )
                parsed = None
                last_error = None
                for attempt in range(1, VIDEO_VALIDATION_ATTEMPTS + 1):
                    try:
                        response = await asyncio.to_thread(
                            generate_response, client, model=self.model, contents=prompt,
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json", temperature=0,
                                seed=DETERMINISTIC_GENERATION_SEED + attempt - 1,
                                candidate_count=1))
                        parsed = _validate_video_batch(_decode(response.text), batch, landing_context)
                        break
                    except Exception as exc:
                        last_error = f"{type(exc).__name__}: {exc}"
                        if attempt < VIDEO_VALIDATION_ATTEMPTS:
                            prompt += ("\nREINTENTO: la respuesta anterior fue inválida: "
                                       f"{last_error}. Corrige únicamente el formato y conserva todos los IDs.")
                if parsed is None:
                    parsed = [{"video_id": item["video_id"], "decision": "requires_review",
                               "language": item.get("audio_language") or item.get("default_language") or "unknown",
                               "reason": f"Bloque no validado tras {VIDEO_VALIDATION_ATTEMPTS} intentos: {last_error}",
                               "evidence": item.get("video_title", ""),
                               "failure_kind": "technical_error"} for item in batch]
                by_id = {str(item["video_id"]): item for item in batch}
                for decision in parsed:
                    source = by_id[str(decision["video_id"])]
                    decisions.append({**source,
                                      "detected_language": decision.get("language", "unknown"),
                                      "relevance_decision": decision["decision"],
                                      "relevance_reason": decision.get("reason", ""),
                                      "relevance_evidence": decision.get("evidence", ""),
                                      **({"selection_reason": decision["selection_reason"]}
                                         if decision.get("selection_reason") else {}),
                                      **({"validation_failure_kind": decision["failure_kind"]}
                                         if decision.get("failure_kind") else {})})
                for query, row in ledger.items():
                    related = [item for item in decisions
                               if query in str(item.get("video_keywords", "")).split("; ")]
                    row["accepted"] = sum(item.get("relevance_decision") == "accepted" for item in related)
                    row["rejected"] = sum(item.get("relevance_decision") == "rejected" for item in related)
                    row["requires_review"] = sum(item.get("relevance_decision") == "requires_review" for item in related)
                payload = json.dumps(decisions, ensure_ascii=False)
                pending = sum(item.get("relevance_decision") == "requires_review" for item in decisions)
                yield emit({"youtube_videos_research": payload, "youtube_search_status": {
                    "status": "validating", "query_count": len(queries),
                    "queries": deepcopy(ledger), "candidate_count": len(raw_candidates),
                    "candidates_decided": len(decisions) - pending,
                    "candidates_review": pending, "current_batch": batch_number,
                    "total_batches": total_batches, "max_candidates_per_query": 50,
                    "validation_batch_size": VIDEO_VALIDATION_BATCH_SIZE, "min_views": 0,
                }}, f"Bloque {batch_number}/{total_batches} guardado: "
                    f"{len(decisions)}/{candidate_count} candidatos procesados.")

            query_errors = sum(row.get("status") == "error" for row in ledger.values())
            pending = sum(item.get("relevance_decision") == "requires_review" for item in decisions)
            accepted = sum(item.get("relevance_decision") == "accepted" for item in decisions)
            rejected = sum(item.get("relevance_decision") == "rejected" for item in decisions)
            complete = not query_errors and not pending and len(decisions) == candidate_count
            status = {
                "status": "complete" if complete else "incomplete",
                "query_count": len(queries), "completed_queries": len(queries) - query_errors,
                "query_error_count": query_errors, "queries": ledger,
                "candidate_count": candidate_count,
                "validated_candidate_count": len(eligible_candidates),
                "candidates_decided": accepted + rejected,
                "candidates_review": pending, "accepted": accepted, "rejected": rejected,
                "max_candidates_per_query": 50,
                "validation_batch_size": VIDEO_VALIDATION_BATCH_SIZE, "min_views": 0,
            }
            yield emit({"youtube_videos_research": json.dumps(decisions, ensure_ascii=False),
                        "youtube_search_status": status},
                       f"Validación de videos terminada: {accepted} aceptados, {rejected} rechazados, "
                       f"{pending} pendientes; {query_errors} consultas con error.")
        except Exception as exc:
            status = {"status": "incomplete", "queries": ledger,
                      "candidate_count": len(candidates_by_id),
                      "candidates_decided": len(decisions),
                      "error": f"{type(exc).__name__}: {exc}",
                      "max_candidates_per_query": 50,
                      "validation_batch_size": VIDEO_VALIDATION_BATCH_SIZE, "min_views": 0}
            yield emit({"youtube_videos_research": json.dumps(decisions, ensure_ascii=False),
                        "youtube_search_status": status},
                       f"Validación de videos incompleta: {status['error']}")
        finally:
            if client is not None:
                await asyncio.to_thread(client.close)


class DeterministicCommentsCollectorAgent(LlmAgent):
    """Publish the tool result without model re-serialisation."""

    async def _run_async_impl(self, ctx):
        def emit(delta, text=None):
            ctx.session.state.update(delta)
            return Event(author=self.name, invocation_id=ctx.invocation_id,
                         branch=ctx.branch, actions=EventActions(state_delta=delta),
                         content=types.Content(role="model", parts=[types.Part.from_text(text=text)]) if text else None)

        saved = ctx.session.state.get("youtube_comments_collected") if ctx.session.state.get("comments_resume") else None
        candidate_count = accepted_count = rejected_count = 0
        yield emit({"youtube_comments_collected": saved,
                    "youtube_comments_collection_status": {"status": "collecting", "invocation_id": ctx.invocation_id}})
        try:
            if saved:
                result = _decode(saved)
            else:
                candidates = _decode(ctx.session.state.get("youtube_videos_research"))
                if not isinstance(candidates, list):
                    raise ValueError("La validación de videos no devolvió una lista")
                candidate_count = len(candidates)
                videos = [item for item in candidates if isinstance(item, dict)
                          and item.get("relevance_decision") == "accepted"
                          and str(item.get("detected_language", "")).lower().startswith("es")]
                accepted_count = len(videos)
                rejected_count = candidate_count - accepted_count
                if not videos:
                    raise ValueError("Ningún candidato superó la validación semántica contra la landing")
                yield emit({"youtube_comments_collection_status": {
                    "status": "collecting", "invocation_id": ctx.invocation_id,
                    "candidate_count": candidate_count, "accepted_videos": accepted_count,
                    "rejected_videos": rejected_count,
                }}, f"Validación de videos terminada: {accepted_count} aceptados y "
                     f"{rejected_count} rechazados. Recolectando comentarios solo de los aceptados.")
                result = await asyncio.to_thread(
                    extract_comments_from_videos, videos, include_excluded=True)
            if not isinstance(result, list) or not result:
                raise ValueError("No hay videos recolectados para procesar")
            result, consolidation = _consolidate_videos(result)
            collection_recovery = ctx.session.state.get('youtube_collection_recovery') or {}
            if not saved:
                collection_recovery = {'round': 0, 'deadline': time.time() + RECOVERY_SECONDS}
            collection_recovery.setdefault('deadline', time.time() + RECOVERY_SECONDS)
            for attempt in range(collection_recovery.get('round', 0) + 1, RECOVERY_ROUNDS + 1):
                pending = _problems(result)
                if not pending or time.time() >= collection_recovery['deadline']:
                    break
                collection_recovery = {**collection_recovery, 'round': attempt, 'status': 'recovering',
                                       'pending_videos': [x.get('video_href') for x in pending]}
                yield emit({"youtube_comments_collected": json.dumps(result, ensure_ascii=False),
                            'youtube_collection_recovery': dict(collection_recovery),
                            "youtube_comments_collection_status": {
                                "status": "recovering", "invocation_id": ctx.invocation_id,
                                "attempt": attempt, "partial_videos": len(pending)}},
                           f"Recuperando {len(pending)} video(s) con extracción parcial, intento {attempt}/{RECOVERY_ROUNDS}. "
                           "Los comentarios ya recolectados se conservan.")
                for problem in pending:
                    if time.time() >= collection_recovery['deadline']:
                        break
                    try:
                        recovered = await asyncio.to_thread(extract_comments_from_videos,
                                                          [problem], include_excluded=True)
                        replacement = next((v for v in recovered if v.get("video_href") == problem.get("video_href")), None)
                        if replacement is not None:
                            merged_recovery, _ = _consolidate_videos([problem, replacement])
                            result[result.index(problem)] = merged_recovery[0]
                        yield emit({'youtube_comments_collected': json.dumps(result, ensure_ascii=False)},
                                   'Avance de extracción recuperado y guardado.')
                    except Exception as exc:
                        problem["recovery_error"] = type(exc).__name__
            partial = _problems(result)
            collection_recovery.update(status='finished', pending_videos=[x.get('video_href') for x in partial])
            payload = json.dumps(result, ensure_ascii=False)
            count = sum(len(v.get("3_months_comments", [])) for v in result)
            message = (f"Recolección terminada: {count} comentarios únicos de {len(result)} videos únicos. "
                       f"Se consolidaron {consolidation['duplicate_videos']} videos y "
                       f"{consolidation['duplicate_comments']} comentarios repetidos. ")
            if partial:
                message += (f"Persisten {len(partial)} video(s) con extracción parcial: "
                            + ", ".join(v.get("video_href", "URL desconocida") for v in partial)
                            + ". Se clasificarán los comentarios disponibles; el informe indicará la limitación.")
            else:
                message += "Iniciando clasificación."
            yield emit({"youtube_comments_collected": payload,
                        'youtube_collection_recovery': collection_recovery,
                        "youtube_comments_collection_status": {"status": "complete" if not partial else "incomplete",
                        "invocation_id": ctx.invocation_id, "videos": len(result), "partial_videos": len(partial),
                        "candidate_count": candidate_count, "accepted_videos": accepted_count,
                        "rejected_videos": rejected_count,
                        "comment_count": count, "consolidation": consolidation, "issues": [{k: v.get(k) for k in
                        ("video_href", "collection_status", "collection_error")} for v in partial]}}, message)
        except Exception as exc:
            yield emit({"youtube_comments_collected": None,
                        "youtube_comments_collection_status": {"status": "error", "invocation_id": ctx.invocation_id,
                        "candidate_count": candidate_count, "accepted_videos": accepted_count,
                        "rejected_videos": rejected_count,
                        "error": f"{type(exc).__name__}: {exc}"}}, f"Extracción detenida: {exc}")


class BatchedCommentsClassifierAgent(LlmAgent):
    """Classify bounded batches and require one decision per source id."""

    async def _run_async_impl(self, ctx):
        def emit(delta, text=None):
            ctx.session.state.update(delta)
            return Event(author=self.name, invocation_id=ctx.invocation_id,
                         branch=ctx.branch, actions=EventActions(state_delta=delta),
                         content=types.Content(role="model", parts=[types.Part.from_text(text=text)]) if text else None)

        results = []
        client = None
        source = []
        try:
            collected = _decode(ctx.session.state.get("youtube_comments_collected")) or []
            source = []
            for video in collected:
                source.extend(video.get("3_months_comments", []))
            invalid_source_count = sum(1 for item in source if not item.get("comment_id"))
            source = [item for item in source if item.get("comment_id")]
            if len({item["comment_id"] for item in source}) != len(source):
                raise ValueError("La extracción contiene identificadores repetidos; no se puede demostrar cobertura")
            landing = _decode(ctx.session.state.get("landing_page_research")) or {}
            categories = {f"D{i+1}": value for i, value in enumerate(landing.get("deseos", []))}
            categories.update({f"P{i+1}": value for i, value in enumerate(landing.get("problemas", []))})
            fingerprint = _fingerprint({"source": source, "categories": categories, "model": str(self.model)})
            saved = ctx.session.state.get("youtube_comments_checkpoint") or {}
            if ctx.session.state.get("comments_resume") and saved.get("fingerprint") == fingerprint:
                previous = _decode(ctx.session.state.get("youtube_comments_classified")) or []
                by_id = {item["comment_id"]: item for item in source}
                for item in previous:
                    original = by_id.get(item.get("comment_id"))
                    if original:
                        _validate_batch([item], [original], categories)
                        results.append(item)
                if len({item['comment_id'] for item in results}) != len(results):
                    raise ValueError("El punto de recuperación contiene duplicados")
            # Reuse validated per-comment decisions.  The cache key includes
            # the text, categories and model so stale decisions cannot leak
            # into a changed landing-page analysis.
            cache = ctx.session.state.get("youtube_comments_classification_cache") or {}
            if isinstance(cache, str):
                cache = _decode(cache) or {}
            for original in source:
                key = _fingerprint({"id": str(original["comment_id"]), "msg": original.get("Msg", ""),
                                    "categories": categories, "model": str(self.model), "v": 2})
                cached = cache.get(key) if isinstance(cache, dict) else None
                if isinstance(cached, dict) and cached.get("decision") in {"deseo", "problema", "no_aplica"}:
                    try:
                        _validate_batch([cached], [original], categories)
                        if str(original["comment_id"]) not in {str(x.get("comment_id")) for x in results}:
                            results.append(cached)
                    except ValueError:
                        continue
            completed = {str(item["comment_id"]) for item in results}
            desires_count, problems_count = _market_signal_counts(results)
            valid_count = desires_count + problems_count
            if _market_signal_reached(results):
                payload = json.dumps(results, ensure_ascii=False)
                yield emit({"youtube_comments_classified": payload,
                            "youtube_comments_classification_status": {
                                "status": "complete", "invocation_id": ctx.invocation_id,
                                "source_count": len(source), "result_count": len(results),
                                "review_count": sum(1 for x in results if x.get("decision") == "requiere_revision"),
                                "invalid_source_count": invalid_source_count, "target": CLASSIFICATION_TARGET,
                                "desires_count": desires_count, "problems_count": problems_count,
                                "target_reached": True, "stop_reason": "market_signal_threshold"}},
                           f"Se alcanzó el umbral de mercado: {valid_count} deseos/problemas. "
                           "Se detiene la clasificación y se genera el informe.")
                return
            remaining = [item for item in source if str(item["comment_id"]) not in completed]
            pending_batches = (len(remaining) + CLASSIFICATION_BATCH_SIZE - 1) // CLASSIFICATION_BATCH_SIZE
            completed_batches = len(results) // CLASSIFICATION_BATCH_SIZE
            total_batches = completed_batches + pending_batches
            yield emit({"youtube_comments_classification_status": {
                "status": "classifying", "invocation_id": ctx.invocation_id, "source_count": len(source),
                "result_count": len(results), "total_batches": total_batches,
                "invalid_source_count": invalid_source_count}},
                f"Clasificación iniciada: {len(source)} comentarios, {len(results)} ya guardados, "
                f"{pending_batches} lotes pendientes de {total_batches}. "
                f"{invalid_source_count} comentarios sin identificador requieren revisión.")
            client = __import__("google.genai", fromlist=["Client"]).Client(http_options=types.HttpOptions(
                timeout=60000, retry_options=types.HttpRetryOptions(attempts=1)))
            permanent_failure = None
            transient_failure = None
            async def classify_batch(batch_number, batch):
                nonlocal permanent_failure, transient_failure
                prompt = ("Clasifica cada comentario exactamente una vez. Devuelve solo JSON. "
                          "decision debe ser deseo, problema, no_aplica o requiere_revision. "
                          "category_id debe ser D1-D3/P1-P3 o null. Conserva cada comment_id.\n"
                          "Usa exclusivamente el contexto de esta landing; no importes categorías "
                          "ni interpretaciones de otra ejecución. Preguntas, solicitudes de ayuda, "
                          "experiencias personales y testimonios de mejora cuentan cuando expresan "
                          "uno de los seis ejes. no_aplica queda reservado para saludos, emojis, "
                          "agradecimientos sin necesidad, spam o texto ajeno.\n"
                          f"OFERTA={json.dumps(landing.get('offer', {}), ensure_ascii=False)}\n"
                          f"PROMESA={json.dumps(landing.get('main_promise', ''), ensure_ascii=False)}\n"
                          f"AVATAR={json.dumps(landing.get('avatar', {}), ensure_ascii=False)}\n"
                          f"CATEGORIAS={json.dumps(categories, ensure_ascii=False)}\n"
                          f"COMENTARIOS={json.dumps([{k: item.get(k, '') for k in ('comment_id', 'Msg')} for item in batch], ensure_ascii=False)}")
                parsed = None
                last_error = None
                details = {}
                attempts = 0
                for attempt in range(3):
                    if permanent_failure:
                        details = permanent_failure
                        last_error = details['error_type']
                        break
                    attempts += 1
                    try:
                        retry_note = (
                            "\nREINTENTO: corrige este error de la respuesta anterior: "
                            f"{details.get('message')}. Si decision es deseo usa D1-D3; si es "
                            "problema usa P1-P3; para no_aplica o requiere_revision usa null."
                            if attempt and details.get("message") else ""
                        )
                        response = await asyncio.to_thread(
                            generate_response, client, model=self.model,
                            contents=prompt + retry_note,
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json", temperature=0,
                                seed=DETERMINISTIC_GENERATION_SEED + attempt,
                                candidate_count=1),
                        )
                        candidate = _decode(response.text)
                        parsed = _validate_batch(candidate, batch, categories)
                        break
                    except Exception as exc:
                        details = failure_details(exc)
                        last_error = details['error_type']
                        if details.get('error_code') is not None:
                            last_error += f" {details['error_code']}"
                        if details['permanent']:
                            permanent_failure = details
                            break
                        # Persist long waits in the recovery stage instead of
                        # retrying immediately against the provider's limit.
                        if details['transient'] or details['retry_after']:
                            transient_failure = details
                            break
                failed = parsed is None
                if failed:
                    # Preserve coverage and the original identity. These items
                    # remain visible for review instead of silently disappearing.
                    parsed = [{"comment_id": item["comment_id"], "decision": "requiere_revision",
                               "category_id": None, "evidence": "",
                               "failure_kind": "technical_error", "failure": details,
                               "attempts": attempts,
                               "reason": f"Lote no validado tras {attempts} intentos: {last_error}"}
                              for item in batch]
                by_id = {str(item["comment_id"]): item for item in batch}
                materialized = []
                for item in parsed:
                    original = by_id[str(item["comment_id"])]
                    decision = item.get("decision")
                    category_id = item.get("category_id")
                    category = categories.get(category_id) if category_id else None
                    materialized.append({
                        **item,
                        "failure_kind": ("technical_error" if failed
                                         else "semantic_ambiguity" if decision == 'requiere_revision' else None),
                        "attempts": attempts,
                        "categoria": decision if decision in {"deseo", "problema"} else decision,
                        "deseo": category if decision == "deseo" else None,
                        "problema": category if decision == "problema" else None,
                        "Msg": original.get("Msg", ""),
                        "Author": original.get("Author", ""),
                        "video_href": original.get("video_href", ""),
                    })
                return batch_number, materialized, last_error

            for chunk_start in range(0, len(remaining), CLASSIFICATION_BATCH_SIZE * CLASSIFICATION_CONCURRENCY):
                chunk = [remaining[i:i + CLASSIFICATION_BATCH_SIZE]
                         for i in range(chunk_start, min(len(remaining), chunk_start + CLASSIFICATION_BATCH_SIZE * CLASSIFICATION_CONCURRENCY), CLASSIFICATION_BATCH_SIZE)]
                first_batch = completed_batches + chunk_start // CLASSIFICATION_BATCH_SIZE + 1
                tasks = [asyncio.create_task(classify_batch(first_batch + offset, batch))
                         for offset, batch in enumerate(chunk)]
                try:
                    yield emit({"youtube_comments_classification_status": {
                        "status": "classifying", "invocation_id": ctx.invocation_id,
                        "batch": first_batch, "total_batches": total_batches,
                        "concurrency": CLASSIFICATION_CONCURRENCY,
                        "result_count": len(results), "source_count": len(source)}},
                        ((f"Clasificando lote {first_batch}/{total_batches} "
                          if CLASSIFICATION_CONCURRENCY == 1 else
                          f"Clasificando lote {first_batch}/{total_batches}, hasta {CLASSIFICATION_CONCURRENCY} en paralelo ")
                         + f"({len(results)}/{len(source)} comentarios guardados)."))
                    if CLASSIFICATION_CONCURRENCY > 1:
                        for offset in range(len(chunk)):
                            yield emit({}, f"Clasificando lote {first_batch + offset}/{total_batches} en paralelo.")
                    for completed_batch in asyncio.as_completed(tasks):
                        batch_number, materialized, _ = await completed_batch
                        results.extend(materialized)
                        for item in materialized:
                            if item.get("decision") in {"deseo", "problema", "no_aplica"}:
                                cache[_fingerprint({"id": str(item["comment_id"]), "msg": item.get("Msg", ""),
                                                    "categories": categories, "model": str(self.model), "v": 2})] = item
                        desires_count, problems_count = _market_signal_counts(results)
                        valid_count = desires_count + problems_count
                        yield emit({"youtube_comments_classified": json.dumps(results, ensure_ascii=False),
                                    "youtube_comments_classification_cache": dict(cache),
                                    "youtube_comments_checkpoint": {"fingerprint": fingerprint, "result_count": len(results)}},
                                   f"Lote {batch_number} guardado: {len(results)}/{len(source)} comentarios; "
                                   f"deseos: {desires_count}; problemas: {problems_count}; "
                                   f"total relevante: {valid_count}/{CLASSIFICATION_TARGET}.")
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                if _market_signal_reached(results):
                    break
                if permanent_failure or transient_failure:
                    break

            recovery = ctx.session.state.get('youtube_comments_recovery') or {}
            if recovery.get('fingerprint') != fingerprint:
                recovery = {'fingerprint': fingerprint, 'round': 0,
                            'deadline': time.time() + RECOVERY_SECONDS}
            by_source = {str(x['comment_id']): x for x in source}
            if transient_failure:
                completed_ids = {str(item.get('comment_id')) for item in results}
                for original in source:
                    if str(original['comment_id']) in completed_ids:
                        continue
                    results.append({
                        "comment_id": original["comment_id"], "decision": "requiere_revision",
                        "category_id": None, "evidence": "", "failure_kind": "technical_error",
                        "failure": transient_failure, "attempts": 0,
                        "reason": f"Pendiente por {transient_failure['error_type']} "
                                  f"{transient_failure.get('error_code') or ''}".strip(),
                        "categoria": "requiere_revision", "deseo": None, "problema": None,
                        "Msg": original.get("Msg", ""), "Author": original.get("Author", ""),
                        "video_href": original.get("video_href", ""),
                    })
            for round_number in range(int(recovery.get('round', 0)) + 1, RECOVERY_ROUNDS + 1):
                pending = [x for x in results if technical_pending(x)]
                if not pending or _market_signal_reached(results) or permanent_failure:
                    break
                if time.time() >= recovery['deadline']:
                    break
                delay = max([2 ** round_number] + [x.get('failure', {}).get('retry_after', 0) for x in pending])
                next_retry = max(time.time() + delay, recovery.get('next_retry_at', 0))
                if next_retry >= recovery['deadline']:
                    recovery['wait_exceeds_deadline'] = True
                    break
                recovery = {**recovery, 'status': 'recovering', 'round': round_number,
                            'pending_ids': [x['comment_id'] for x in pending],
                            'next_retry_at': next_retry, 'stage': 'classification',
                            'last_error': pending[-1].get('reason')}
                yield emit({'youtube_comments_recovery': dict(recovery)},
                           f'Recuperación automática {round_number}/{RECOVERY_ROUNDS}: '
                           f'{len(pending)} comentarios con errores técnicos. '
                           f'Se conservan {len(results) - len(pending)} decisiones restantes.')
                await asyncio.sleep(max(0, next_retry - time.time()))
                transient_failure = None
                batch_size = 10 if round_number == 1 else 5 if round_number == 2 else 1
                before = len(pending)
                for start in range(0, len(pending), batch_size):
                    if time.time() >= recovery['deadline'] or permanent_failure:
                        break
                    batch = [by_source[str(x['comment_id'])] for x in pending[start:start + batch_size]]
                    _, repaired, _ = await classify_batch(start // batch_size + 1, batch)
                    replacements = {str(x['comment_id']): x for x in repaired}
                    for old in results:
                        new = replacements.get(str(old['comment_id']))
                        if new:
                            new['attempts'] = old.get('attempts', 0) + new.get('attempts', 0)
                    results = [replacements.get(str(x['comment_id']), x) for x in results]
                    for item in repaired:
                        if item.get('decision') in {'deseo', 'problema', 'no_aplica'}:
                            cache[_fingerprint({'id': str(item['comment_id']), 'msg': item.get('Msg', ''),
                                                'categories': categories, 'model': str(self.model), 'v': 2})] = item
                    pending_ids = [x['comment_id'] for x in results if technical_pending(x)]
                    recovery = {**recovery, 'pending_ids': pending_ids, 'next_retry_at': 0}
                    desires_count, problems_count = _market_signal_counts(results)
                    valid_count = desires_count + problems_count
                    yield emit({'youtube_comments_classified': json.dumps(results, ensure_ascii=False),
                                'youtube_comments_checkpoint': {'fingerprint': fingerprint, 'result_count': len(results)},
                                'youtube_comments_classification_cache': dict(cache),
                                'youtube_comments_recovery': dict(recovery)},
                               f'Recuperación {round_number}: {len(pending_ids)} errores técnicos pendientes; '
                               f'{valid_count}/{CLASSIFICATION_TARGET} deseos o problemas.')
                    if _market_signal_reached(results):
                        break
                    if transient_failure:
                        break
                recovery['progress'] = before - sum(technical_pending(x) for x in results)
            technical_count = sum(technical_pending(x) for x in results)
            recovery = {**recovery, 'status': 'finished',
                        'pending_ids': [x['comment_id'] for x in results if technical_pending(x)],
                        'stop_reason': ('target_reached' if _market_signal_reached(results) else
                                        'permanent_error' if permanent_failure else
                                        'resolved' if not technical_count else
                                        'rate_limited' if transient_failure and transient_failure.get('rate_limited') else
                                        'deadline' if time.time() >= recovery['deadline'] or recovery.get('wait_exceeds_deadline') else 'attempts_exhausted')}
            yield emit({'youtube_comments_recovery': recovery},
                       f'Recuperación finalizada: {technical_count} errores técnicos pendientes.')
            payload = json.dumps(results, ensure_ascii=False)
            review_count = sum(1 for item in results if item.get("decision") == "requiere_revision")
            desires_count, problems_count = _market_signal_counts(results)
            target_reached = _market_signal_reached(results)
            yield emit({"youtube_comments_classified": payload,
                        "youtube_comments_classification_status": {"status": "complete", "invocation_id": ctx.invocation_id,
                        "source_count": len(source), "result_count": len(results), "review_count": review_count,
                        "technical_error_count": technical_count, "semantic_review_count": review_count - technical_count,
                        "invalid_source_count": invalid_source_count, "target": CLASSIFICATION_TARGET,
                        "desires_count": desires_count, "problems_count": problems_count,
                        "target_reached": target_reached,
                        "stop_reason": "market_signal_threshold" if target_reached else "source_exhausted"}}, payload)
        except Exception as exc:
            yield emit({"youtube_comments_classified": json.dumps(results, ensure_ascii=False),
                        "youtube_comments_classification_status": {"status": "error", "invocation_id": ctx.invocation_id,
                        "result_count": len(results), "source_count": len(source),
                        "error": type(exc).__name__}}, f"Clasificación detenida ({type(exc).__name__}). "
                        f"Se conservaron {len(results)} decisiones. El informe indicará el error pendiente.")
        finally:
            if client is not None:
                await asyncio.to_thread(client.close)
