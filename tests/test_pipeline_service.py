from pathlib import Path

from src.services import pipeline_service


def test_resolve_default_guide_prefers_latest_weekly_output(tmp_path: Path) -> None:
    program_dir = tmp_path / "program"
    output_dir = program_dir / "output"
    output_dir.mkdir(parents=True)
    baseline = program_dir / "guide.md"
    latest = output_dir / "sponsor_guide_updated.md"
    baseline.write_text("baseline", encoding="utf-8")
    latest.write_text("latest", encoding="utf-8")

    assert pipeline_service._resolve_default_guide(program_dir) == latest


def test_artifacts_from_logs_returns_current_run_saved_paths() -> None:
    logs = "\n".join(
        [
            "step=5 artifact=markdown status=saved path=programs/test/output/sponsor_guide_updated.md",
            "step=5 artifact=markdown_timestamped status=saved path=programs/test/output/sponsor_guide_updated_20260430_120000.md",
            "step=5 artifact=markdown status=saved path=programs/test/output/sponsor_guide_updated.md",
        ]
    )

    assert pipeline_service._artifacts_from_logs(logs) == [
        "programs/test/output/sponsor_guide_updated.md",
        "programs/test/output/sponsor_guide_updated_20260430_120000.md",
    ]
