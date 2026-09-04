"""Deterministic orchestration for comment collection."""

import asyncio
import hashlib
import json
import os
from copy import deepcopy
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.events import Event, EventActions
from google.genai import types

from .tools.youtube_comment_extractor_tool import extract_comments_from_videos

CLASSIFICATION_BATCH_SIZE = max(1, int(os.getenv("COMMENTS_BATCH_SIZE", "25")))
CLASSIFICATION_CONCURRENCY = max(1, int(os.getenv("COMMENTS_CONCURRENCY", "4")))
CLASSIFICATION_TARGET = max(1, int(os.getenv("COMMENTS_TARGET", "100")))


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


class DeterministicCommentsCollectorAgent(LlmAgent):
    """Publish the tool result without model re-serialisation."""

    async def _run_async_impl(self, ctx):
        def emit(delta, text=None):
            ctx.session.state.update(delta)
            return Event(author=self.name, invocation_id=ctx.invocation_id,
                         branch=ctx.branch, actions=EventActions(state_delta=delta),
                         content=types.Content(role="model", parts=[types.Part.from_text(text=text)]) if text else None)

        saved = ctx.session.state.get("youtube_comments_collected") if ctx.session.state.get("comments_resume") else None
        yield emit({"youtube_comments_collected": saved,
                    "youtube_comments_collection_status": {"status": "collecting", "invocation_id": ctx.invocation_id}})
        try:
            videos = _decode(ctx.session.state.get("youtube_videos_research"))
            result = _decode(saved) if saved else await asyncio.to_thread(extract_comments_from_videos, videos, include_excluded=True)
            if not isinstance(result, list) or not result:
                raise ValueError("No hay videos recolectados para procesar")
            result, consolidation = _consolidate_videos(result)
            for attempt in range(1, 3):
                pending = _problems(result)
                if not pending:
                    break
                yield emit({"youtube_comments_collected": json.dumps(result, ensure_ascii=False),
                            "youtube_comments_collection_status": {
                                "status": "recovering", "invocation_id": ctx.invocation_id,
                                "attempt": attempt, "partial_videos": len(pending)}},
                           f"Recuperando {len(pending)} video(s) con extracción parcial, intento {attempt}/2. "
                           "Los comentarios ya recolectados se conservan.")
                for problem in pending:
                    try:
                        recovered = await asyncio.to_thread(extract_comments_from_videos,
                                                          [problem], include_excluded=True)
                        replacement = next((v for v in recovered if v.get("video_href") == problem.get("video_href")
                                            and v.get("collection_status") == "complete"), None)
                        if replacement is not None:
                            merged_recovery, _ = _consolidate_videos([problem, replacement])
                            result[result.index(problem)] = merged_recovery[0]
                    except Exception as exc:
                        problem["recovery_error"] = type(exc).__name__
            partial = _problems(result)
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
                        "youtube_comments_collection_status": {"status": "complete" if not partial else "incomplete",
                        "invocation_id": ctx.invocation_id, "videos": len(result), "partial_videos": len(partial),
                        "comment_count": count, "consolidation": consolidation, "issues": [{k: v.get(k) for k in
                        ("video_href", "collection_status", "collection_error")} for v in partial]}}, message)
        except Exception as exc:
            yield emit({"youtube_comments_collected": None,
                        "youtube_comments_collection_status": {"status": "error", "invocation_id": ctx.invocation_id,
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
                    if original and item.get("decision") != "requiere_revision":
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
            valid_count = sum(1 for item in results if item.get("decision") in {"deseo", "problema"})
            if valid_count >= CLASSIFICATION_TARGET:
                payload = json.dumps(results, ensure_ascii=False)
                yield emit({"youtube_comments_classified": payload,
                            "youtube_comments_classification_status": {
                                "status": "complete", "invocation_id": ctx.invocation_id,
                                "source_count": len(source), "result_count": len(results),
                                "review_count": sum(1 for x in results if x.get("decision") == "requiere_revision"),
                                "invalid_source_count": invalid_source_count, "target": CLASSIFICATION_TARGET,
                                "target_reached": True, "stop_reason": "market_signal_threshold"}},
                           f"Se alcanzó el umbral de mercado: {valid_count} deseos/problemas. "
                           "Se detiene la clasificación y se genera el informe.")
                return
            remaining = [item for item in source if item["comment_id"] not in completed]
            total_batches = (len(remaining) + CLASSIFICATION_BATCH_SIZE - 1) // CLASSIFICATION_BATCH_SIZE
            yield emit({"youtube_comments_classification_status": {
                "status": "classifying", "invocation_id": ctx.invocation_id, "source_count": len(source),
                "result_count": len(results), "total_batches": total_batches,
                "invalid_source_count": invalid_source_count}},
                f"Clasificación iniciada: {len(source)} comentarios, {len(results)} ya guardados, "
                f"{total_batches} lotes pendientes. {invalid_source_count} comentarios sin identificador requieren revisión.")
            client = __import__("google.genai", fromlist=["Client"]).Client(http_options=types.HttpOptions(
                timeout=60000, retry_options=types.HttpRetryOptions(attempts=1)))
            async def classify_batch(batch_number, batch):
                prompt = ("Clasifica cada comentario exactamente una vez. Devuelve solo JSON. "
                          "decision debe ser deseo, problema, no_aplica o requiere_revision. "
                          "category_id debe ser D1-D3/P1-P3 o null. Conserva cada comment_id.\n"
                          f"CATEGORIAS={json.dumps(categories, ensure_ascii=False)}\n"
                          f"COMENTARIOS={json.dumps([{k: item.get(k, '') for k in ('comment_id', 'Msg')} for item in batch], ensure_ascii=False)}")
                parsed = None
                last_error = None
                for attempt in range(3):
                    try:
                        response = await asyncio.to_thread(
                            client.models.generate_content, model=self.model,
                            contents=prompt,
                            config=types.GenerateContentConfig(response_mime_type="application/json"),
                        )
                        candidate = _decode(response.text)
                        parsed = _validate_batch(candidate, batch, categories)
                        break
                    except Exception as exc:
                        last_error = type(exc).__name__
                if parsed is None:
                    # Preserve coverage and the original identity. These items
                    # remain visible for review instead of silently disappearing.
                    parsed = [{"comment_id": item["comment_id"], "decision": "requiere_revision",
                               "category_id": None, "evidence": "",
                               "reason": f"Lote no validado tras 3 intentos: {last_error}"}
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
                first_batch = chunk_start // CLASSIFICATION_BATCH_SIZE + 1
                yield emit({"youtube_comments_classification_status": {
                    "status": "classifying", "invocation_id": ctx.invocation_id,
                    "batch": first_batch, "total_batches": total_batches, "concurrency": CLASSIFICATION_CONCURRENCY,
                    "result_count": len(results), "source_count": len(source)}},
                    (f"Clasificando lote {first_batch}/{total_batches}, hasta {CLASSIFICATION_CONCURRENCY} en paralelo "
                     f"({len(results)}/{len(source)} comentarios guardados)."))
                for offset in range(len(chunk)):
                    yield emit({}, f"Clasificando lote {first_batch + offset}/{total_batches} en paralelo.")
                completed_batches = await asyncio.gather(*[
                    classify_batch(first_batch + offset, batch) for offset, batch in enumerate(chunk)
                ])
                for _, materialized, _ in sorted(completed_batches, key=lambda x: x[0]):
                    results.extend(materialized)
                    for item in materialized:
                        if item.get("decision") in {"deseo", "problema", "no_aplica"}:
                            original = next((x for x in source if str(x["comment_id"]) == str(item["comment_id"])), item)
                            cache[_fingerprint({"id": str(item["comment_id"]), "msg": original.get("Msg", ""),
                                                "categories": categories, "model": str(self.model), "v": 2})] = item
                valid_count = sum(1 for item in results if item.get("decision") in {"deseo", "problema"})
                yield emit({"youtube_comments_classified": json.dumps(results, ensure_ascii=False),
                            "youtube_comments_classification_cache": cache,
                            "youtube_comments_checkpoint": {"fingerprint": fingerprint, "result_count": len(results)}},
                           f"Lotes guardados: {len(results)}/{len(source)} comentarios; "
                           f"señales válidas: {valid_count}/{CLASSIFICATION_TARGET}.")
                if valid_count >= CLASSIFICATION_TARGET:
                    break
            payload = json.dumps(results, ensure_ascii=False)
            review_count = sum(1 for item in results if item.get("decision") == "requiere_revision")
            target_reached = sum(1 for item in results if item.get("decision") in {"deseo", "problema"}) >= CLASSIFICATION_TARGET
            yield emit({"youtube_comments_classified": payload,
                        "youtube_comments_classification_status": {"status": "complete", "invocation_id": ctx.invocation_id,
                        "source_count": len(source), "result_count": len(results), "review_count": review_count,
                        "invalid_source_count": invalid_source_count, "target": CLASSIFICATION_TARGET,
                        "target_reached": target_reached,
                        "stop_reason": "market_signal_threshold" if target_reached else "source_exhausted"}}, payload)
        except Exception as exc:
            yield emit({"youtube_comments_classified": json.dumps(results, ensure_ascii=False),
                        "youtube_comments_classification_status": {"status": "error", "invocation_id": ctx.invocation_id,
                        "result_count": len(results), "source_count": len(source),
                        "error": type(exc).__name__}}, f"Clasificación detenida ({type(exc).__name__}). "
                        f"Se conservaron {len(results)} decisiones. Envía «reanuda» para continuar con los datos guardados.")
        finally:
            if client is not None:
                await asyncio.to_thread(client.close)
