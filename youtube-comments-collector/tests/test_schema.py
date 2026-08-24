import pytest
import jsonschema
from youtube_scraper.models import validate_comments_data, YouTubeComment, YOUTUBE_COMMENTS_SCHEMA


def test_schema_valid_data():
    valid_data = [
        {
            "URL": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "Title": "Never Gonna Give You Up",
            "Video Title": "Never Gonna Give You Up",
            "Author": "Rick Astley",
            "Msg": "Never gonna give you up!",
            "Reply": []
        },
        {
            "URL": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "Title": "Never Gonna Give You Up",
            "Video Title": "Never Gonna Give You Up",
            "Author": "Fan 1",
            "Msg": "Awesome song",
            "Reply": [
                {"Author": "Fan 2", "Msg": "Totally agree"}
            ]
        }
    ]
    assert validate_comments_data(valid_data) is True


def test_schema_invalid_missing_fields():
    invalid_data = [
        {
            "URL": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            # Missing "Video Title"
            "Author": "Rick Astley",
            "Msg": "Never gonna give you up!",
            "Reply": []
        }
    ]
    with pytest.raises(jsonschema.ValidationError):
        validate_comments_data(invalid_data)


def test_youtube_comment_to_dict_compliance():
    comment = YouTubeComment(
        URL="https://www.youtube.com/watch?v=abc",
        Title="Sample Video",
        Author="@user-123",
        Msg="Great tutorial!",
        Reply=[{"Author": "@user-456", "Msg": "Thanks!"}]
    )
    d = comment.to_dict()
    assert d["URL"] == "https://www.youtube.com/watch?v=abc"
    assert d["Title"] == "Sample Video"
    assert d["Video Title"] == "Sample Video"
    assert d["Author"] == "@user-123"
    assert d["Msg"] == "Great tutorial!"
    assert len(d["Reply"]) == 1

    # Validate against schema
    assert validate_comments_data([d]) is True
