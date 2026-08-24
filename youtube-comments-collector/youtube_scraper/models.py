"""Data models and JSON schema for YouTube Comments Collector."""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
import jsonschema


YOUTUBE_COMMENTS_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "array",
    "items": {
        "type": "object",
        "required": ["URL", "Video Title", "Author", "Msg", "Reply"],
        "properties": {
            "URL": {"type": "string"},
            "Title": {"type": "string"},
            "Video Title": {"type": "string"},
            "Author": {"type": "string"},
            "Msg": {"type": "string"},
            "Reply": {
                "type": "array",
                "items": {}
            }
        }
    }
}


@dataclass
class CommentReply:
    """Represents a reply to a YouTube comment."""
    Author: str = ""
    Msg: str = ""
    URL: Optional[str] = None
    PublishedTime: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "Author": self.Author,
            "Msg": self.Msg
        }
        if self.URL:
            d["URL"] = self.URL
        if self.PublishedTime:
            d["PublishedTime"] = self.PublishedTime
        return d


@dataclass
class YouTubeComment:
    """Represents a single top-level YouTube comment."""
    URL: str
    Title: str
    Author: str
    Msg: str
    Reply: List[Dict[str, Any]] = field(default_factory=list)
    Video_Title: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert comment to dictionary strictly complying with user schema."""
        video_title = self.Video_Title or self.Title
        return {
            "URL": self.URL,
            "Title": self.Title,
            "Video Title": video_title,
            "Author": self.Author,
            "Msg": self.Msg,
            "Reply": self.Reply
        }


def validate_comments_data(data: List[Dict[str, Any]]) -> bool:
    """Validate comments dataset against the JSON Schema."""
    jsonschema.validate(instance=data, schema=YOUTUBE_COMMENTS_SCHEMA)
    return True
