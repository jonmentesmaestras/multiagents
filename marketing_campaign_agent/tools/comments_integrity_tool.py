"""Deterministic checks for the comment collection/classification contract."""

from collections import Counter
from typing import Any


def _flatten(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened = []
    for item in items:
        children = item.get("3_months_comments")
        if isinstance(children, list):
            flattened.extend(_flatten(children))
        else:
            flattened.append(item)
    return flattened


def validate_comments_integrity(
    source_comments: list[dict[str, Any]],
    classified_comments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return coverage diagnostics without making semantic classifications."""
    source_comments = _flatten(source_comments)
    classified_comments = _flatten(classified_comments)
    source_ids = [str(item.get("comment_id", "")) for item in source_comments]
    result_ids = [str(item.get("comment_id", "")) for item in classified_comments]
    source_counter = Counter(source_ids)
    result_counter = Counter(result_ids)
    missing = sorted(set(source_ids) - set(result_ids))
    unexpected = sorted(set(result_ids) - set(source_ids))
    duplicate_ids = sorted(k for k, count in result_counter.items() if k and count > 1)
    invalid = [
        str(item.get("comment_id", ""))
        for item in classified_comments
        if not item.get("comment_id") or (
            item.get("decision", item.get("categoria"))
            not in {"deseo", "problema", "no_aplica", "requiere_revision"}
        )
    ]
    complete = bool(source_comments) and not (
        any(not item.get("comment_id") for item in source_comments)
        or missing
        or unexpected
        or duplicate_ids
        or invalid
        or len(source_ids) != len(result_ids)
    )
    return {
        "status": "complete" if complete else "incomplete",
        "source_count": len(source_comments),
        "classified_count": len(classified_comments),
        "missing_ids": missing,
        "unexpected_ids": unexpected,
        "duplicate_ids": duplicate_ids,
        "invalid_results": invalid,
        "unclassified_count": len(missing),
        "source_duplicates": sorted(k for k, count in source_counter.items() if k and count > 1),
    }
