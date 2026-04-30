import json
import os
from pathlib import Path
from unittest.mock import patch

from src.services.review_service import (
    add_approved_url_source,
    load_approved_sources,
    remove_approved_source,
    update_approved_source,
)


def _make_program(tmp_path: Path) -> str:
    slug = "test_program"
    program_dir = tmp_path / "programs" / slug
    program_dir.mkdir(parents=True)
    (program_dir / "sources.json").write_text(
        json.dumps(
            [
                {
                    "name": "existing_source",
                    "url": "https://www.energy.gov/science",
                    "file_path": "",
                    "sections": ["Program Overview"],
                    "data_class": "public",
                }
            ]
        ),
        encoding="utf-8",
    )
    return slug


@patch("src.services.review_service.persist_paths")
def test_weekly_source_management_add_update_and_remove(mock_persist_paths, tmp_path: Path) -> None:
    mock_persist_paths.return_value = {"ok": True, "enabled": False, "message": "Remote persistence disabled."}
    cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        slug = _make_program(tmp_path)

        added = add_approved_url_source(
            slug,
            "https://science.osti.gov/early-career",
            title="DOE Early Career",
            sections_text="Eligibility, Key Dates",
        )
        assert added["ok"]
        new_name = added["entry"]["name"]

        loaded = load_approved_sources(slug)
        assert loaded["ok"]
        assert loaded["count"] == 2
        assert any(src["name"] == new_name for src in loaded["sources"])

        updated = update_approved_source(
            slug,
            new_name,
            title="DOE ECRP",
            url="https://science.osti.gov/early-career",
            sections_text="Award Size & Budget",
        )
        assert updated["ok"]
        assert updated["entry"]["title"] == "DOE ECRP"
        assert updated["entry"]["sections"] == ["Award Size & Budget"]

        removed = remove_approved_source(slug, new_name)
        assert removed["ok"]
        assert removed["count"] == 1
    finally:
        os.chdir(cwd)


@patch("src.services.review_service.persist_paths")
def test_weekly_source_management_prevents_removing_last_source(mock_persist_paths, tmp_path: Path) -> None:
    mock_persist_paths.return_value = {"ok": True, "enabled": False, "message": "Remote persistence disabled."}
    cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        slug = _make_program(tmp_path)

        removed = remove_approved_source(slug, "existing_source")

        assert not removed["ok"]
        assert "last source" in removed["error"]
    finally:
        os.chdir(cwd)
