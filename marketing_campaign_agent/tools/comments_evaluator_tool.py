"""Tool for evaluating classified YouTube comments metrics and determining campaign viability."""

import json
import logging
from typing import Any, Union

logger = logging.getLogger(__name__)


def _parse_classified_comments(classified_comments: Union[list[dict[str, Any]], str, Any]) -> list[dict[str, Any]]:
    """Parses various input formats into a list of classified comment dictionaries."""
    if not classified_comments:
        return []

    if isinstance(classified_comments, str):
        cleaned = classified_comments.strip()
        if (cleaned.startswith("[") and cleaned.endswith("]")) or (
            cleaned.startswith("{") and cleaned.endswith("}")
        ):
            try:
                deserialized = json.loads(cleaned, strict=False)
                return _parse_classified_comments(deserialized)
            except Exception:
                pass
        return []

    if isinstance(classified_comments, list):
        items = []
        for item in classified_comments:
            if isinstance(item, dict):
                # If it's a video container with '3_months_comments'
                if "3_months_comments" in item and isinstance(item["3_months_comments"], list):
                    for sub in item["3_months_comments"]:
                        if isinstance(sub, dict):
                            items.append(sub)
                else:
                    items.append(item)
        return items

    if isinstance(classified_comments, dict):
        # In case the input is a dictionary containing a list of items
        if "comments" in classified_comments and isinstance(classified_comments["comments"], list):
            return _parse_classified_comments(classified_comments["comments"])
        if "youtube_comments_classified" in classified_comments and isinstance(
            classified_comments["youtube_comments_classified"], list
        ):
            return _parse_classified_comments(classified_comments["youtube_comments_classified"])
        return [classified_comments]

    return []


def evaluate_classified_comments_metrics(
    classified_comments: Union[list[dict[str, Any]], str, Any],
    source_comments: Union[list[dict[str, Any]], str, Any, None] = None,
) -> dict[str, Any]:
    """Evaluates the classified comments dataset against market traction thresholds
    (>50 in deseos, >50 in problemas, or >=100 total combined) to determine whether
    to accept the offer and proceed with a Spanish clone.

    Args:
        classified_comments: List of classified comment objects or serialized JSON string.
            Expected items have keys: 'categoria' ('deseo' | 'problema'), 'Msg', 'razon', 'video_href'.

    Returns:
        Dictionary with quantitative counts, threshold evaluations, decision, and recommendation:
        {
            "deseos_count": int,
            "problemas_count": int,
            "total_classified": int,
            "deseos_above_50": bool,
            "problemas_above_50": bool,
            "total_above_100": bool,
            "is_offer_accepted": bool,
            "decision": "ACCEPT_OFFER" | "DO_NOT_ACCEPT_OFFER",
            "conclusion": str,
            "recommendation": str,
            "summary": dict
        }
    """
    comments = _parse_classified_comments(classified_comments)
    coverage = {"status": "unverified"}
    if source_comments is not None:
        source = _parse_classified_comments(source_comments)
        source_ids = [str(item.get("comment_id", "")) for item in source]
        result_ids = [str(item.get("comment_id", "")) for item in comments]
        source_set, result_set = set(source_ids), set(result_ids)
        duplicate_ids = len(result_ids) - len(result_set)
        missing_ids = sorted(source_set - result_set)
        unexpected_ids = sorted(result_set - source_set)
        missing_id_count = sum(1 for value in source_ids if not value)
        coverage = {
            "status": "verified" if not (missing_id_count or duplicate_ids or missing_ids or unexpected_ids) else "incomplete",
            "source_count": len(source),
            "classified_count": len(comments),
            "missing_ids": missing_ids,
            "unexpected_ids": unexpected_ids,
            "duplicate_ids": duplicate_ids,
            "source_items_without_id": missing_id_count,
        }
    logger.info(f"[Comments Evaluator] Evaluating {len(comments)} classified comments.")

    deseos_count = 0
    problemas_count = 0

    for item in comments:
        categoria = str(item.get("categoria", "")).strip().lower()
        if categoria == "deseo" or ("deseo" in item and "problema" not in item):
            deseos_count += 1
        elif categoria == "problema" or ("problema" in item and "deseo" not in item):
            problemas_count += 1
        else:
            # Fallback check based on keys
            if item.get("deseo"):
                deseos_count += 1
            elif item.get("problema"):
                problemas_count += 1

    total_classified = deseos_count + problemas_count

    deseos_above_50 = deseos_count > 50
    problemas_above_50 = problemas_count > 50
    total_above_100 = total_classified >= 100

    # Decision logic:
    # 1. Are there more than 50 comments in deseos?
    # 2. If not, are there more than 50 comments in problems?
    # 3. If sum up deseos and problems all together is up to 100 -> validated traction.
    # Otherwise -> insufficient traction.
    coverage_verified = coverage["status"] in {"verified", "unverified"}
    is_offer_accepted = coverage_verified and (deseos_above_50 or problemas_above_50 or total_above_100)

    if is_offer_accepted:
        decision = "ACCEPT_OFFER"
        conclusion = (
            f"La landing page de Brasil cuenta con suficiente volumen de audiencia comentando activamente "
            f"en YouTube en español (Deseos: {deseos_count}, Problemas: {problemas_count}, Total: {total_classified})."
        )
        recommendation = (
            "Se recomienda al usuario considerar continuar con el siguiente paso de la investigación "
            "y avanzar con el desarrollo de la oferta / clon adaptado al español."
        )
    else:
        decision = "DO_NOT_ACCEPT_OFFER"
        conclusion = (
            f"El problema o deseo de la landing page de Brasil actualmente NO cuenta con suficiente audiencia "
            f"comentando en YouTube en español (Deseos: {deseos_count} <= 50, Problemas: {problemas_count} <= 50, "
            f"Total: {total_classified} < 100)."
        )
        recommendation = (
            "Se recomienda al usuario profundizar más en la investigación o explorar otros ángulos y "
            "NO proceder con ningún clon en español por ahora."
        )

    return {
        "deseos_count": deseos_count,
        "problemas_count": problemas_count,
        "total_classified": total_classified,
        "deseos_above_50": deseos_above_50,
        "problemas_above_50": problemas_above_50,
        "total_above_100": total_above_100,
        "is_offer_accepted": is_offer_accepted,
        "decision": decision,
        "conclusion": conclusion,
        "recommendation": recommendation,
        "summary": {
            "deseos": deseos_count,
            "problemas": problemas_count,
            "total": total_classified,
            "status": "APPROVED" if is_offer_accepted else "REJECTED",
        },
        "coverage": coverage,
    }
