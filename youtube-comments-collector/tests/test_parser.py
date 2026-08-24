import pytest
from youtube_scraper.parser import (
    parse_comment_count,
    parse_relative_time_months,
    is_within_time_limit
)


def test_parse_simple_counts():
    assert parse_comment_count("4") == 4
    assert parse_comment_count("4 Comments") == 4
    assert parse_comment_count("4 comentarios") == 4
    assert parse_comment_count("0 Comments") == 0
    assert parse_comment_count("500 Comments") == 500
    assert parse_comment_count("501 Comments") == 501


def test_parse_formatted_numbers():
    assert parse_comment_count("1,234 Comments") == 1234
    assert parse_comment_count("1.234 comentarios") == 1234
    assert parse_comment_count("12 345 Comments") == 12345
    assert parse_comment_count("100,500 comentarios") == 100500


def test_parse_shorthand_notation():
    assert parse_comment_count("1.5K Comments") == 1500
    assert parse_comment_count("15K Comments") == 15000
    assert parse_comment_count("2.3M Comments") == 2300000
    assert parse_comment_count("10 mil comentarios") == 10000


def test_parse_edge_cases():
    assert parse_comment_count("") == 0
    assert parse_comment_count(None) == 0
    assert parse_comment_count("No comments yet") == 0
    assert parse_comment_count("Comments: 42") == 42


def test_parse_relative_time_months():
    assert parse_relative_time_months("just now") == 0.0
    assert parse_relative_time_months("30 seconds ago") == 0.0
    assert parse_relative_time_months("5 minutes ago") == 0.0
    assert parse_relative_time_months("2 hours ago") == 0.0
    assert parse_relative_time_months("1 day ago") < 0.1
    assert parse_relative_time_months("2 weeks ago") < 1.0
    assert parse_relative_time_months("1 month ago") == 1.0
    assert parse_relative_time_months("6 months ago") == 6.0
    assert parse_relative_time_months("6 months ago (edited)") == 6.0
    assert parse_relative_time_months("7 months ago") == 7.0
    assert parse_relative_time_months("1 year ago") == 12.0
    assert parse_relative_time_months("21 years ago") == 252.0

    # Multilingual (Spanish)
    assert parse_relative_time_months("hace 5 minutos") == 0.0
    assert parse_relative_time_months("hace 3 días") < 0.2
    assert parse_relative_time_months("hace 6 meses") == 6.0
    assert parse_relative_time_months("hace 7 meses") == 7.0
    assert parse_relative_time_months("hace 1 año") == 12.0


def test_is_within_time_limit_6_months():
    # <= 6 months should be accepted
    assert is_within_time_limit("just now", max_months=6) is True
    assert is_within_time_limit("10 seconds ago", max_months=6) is True
    assert is_within_time_limit("5 minutes ago", max_months=6) is True
    assert is_within_time_limit("2 hours ago", max_months=6) is True
    assert is_within_time_limit("3 days ago", max_months=6) is True
    assert is_within_time_limit("2 weeks ago", max_months=6) is True
    assert is_within_time_limit("1 month ago", max_months=6) is True
    assert is_within_time_limit("3 months ago", max_months=6) is True
    assert is_within_time_limit("5 months ago", max_months=6) is True
    assert is_within_time_limit("6 months ago", max_months=6) is True
    assert is_within_time_limit("6 months ago (edited)", max_months=6) is True
    assert is_within_time_limit("hace 6 meses", max_months=6) is True

    # >= 7 months or older should be rejected
    assert is_within_time_limit("7 months ago", max_months=6) is False
    assert is_within_time_limit("8 months ago", max_months=6) is False
    assert is_within_time_limit("11 months ago", max_months=6) is False
    assert is_within_time_limit("1 year ago", max_months=6) is False
    assert is_within_time_limit("2 years ago", max_months=6) is False
    assert is_within_time_limit("21 years ago", max_months=6) is False
    assert is_within_time_limit("hace 7 meses", max_months=6) is False
    assert is_within_time_limit("hace 2 años", max_months=6) is False
