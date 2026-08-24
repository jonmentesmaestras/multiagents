"""JSON Exporter and validator for YouTube Comments Collector."""

import json
from pathlib import Path
from typing import List, Dict, Any, Union
from .models import validate_comments_data


def export_comments_to_json(
    comments: List[Dict[str, Any]],
    output_path: Union[str, Path],
    indent: int = 2,
    ensure_ascii: bool = False
) -> Path:
    """
    Validate and save collected comments to a JSON file.
    
    Args:
        comments: List of comment dictionaries.
        output_path: Path to output JSON file.
        indent: Indentation level for JSON formatting.
        ensure_ascii: Whether to escape non-ASCII characters.
        
    Returns:
        Path to the saved JSON file.
    """
    # Ensure compliance with schema before saving
    validate_comments_data(comments)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(comments, f, indent=indent, ensure_ascii=ensure_ascii)

    return path


def dump_comments_json_string(
    comments: List[Dict[str, Any]],
    indent: int = 2,
    ensure_ascii: bool = False
) -> str:
    """Format comments into a validated JSON string."""
    validate_comments_data(comments)
    return json.dumps(comments, indent=indent, ensure_ascii=ensure_ascii)
