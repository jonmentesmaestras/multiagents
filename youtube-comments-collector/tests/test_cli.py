import json
import pytest
from pathlib import Path
from youtube_scraper.cli import main
from tests.test_mock_scraper import MOCK_HTML_LESS_THAN_500


def test_cli_output_file_with_date_filter(tmp_path):
    mock_file = tmp_path / "video.html"
    mock_file.write_text(MOCK_HTML_LESS_THAN_500, encoding="utf-8")
    output_file = tmp_path / "output.json"

    file_url = f"file:///{mock_file.as_posix()}"

    exit_code = main([
        file_url,
        "-o", str(output_file),
        "-m", "5",
        "--max-months", "6",
        "--verbose"
    ])

    assert exit_code == 0
    assert output_file.exists()

    with open(output_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, list)
    # Only 2 comments are within <= 6 months (@alice and @bob), while @old_user (7 months) and @ancient_user (1 year) are excluded
    assert len(data) == 2
    authors = [item["Author"] for item in data]
    assert "@alice" in authors
    assert "@bob" in authors
    assert "@old_user" not in authors
    assert "@ancient_user" not in authors
