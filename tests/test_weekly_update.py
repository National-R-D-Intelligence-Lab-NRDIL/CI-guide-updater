from datetime import date

import weekly_update


def test_decorate_weekly_update_adds_banner_and_highlights_changed_text() -> None:
    old_md = "# Guide\n\n## Key Dates\n\nDeadline: March 1\n\nBudget: $300,000"
    updated_md = "# Guide\n\n## Key Dates\n\nDeadline: April 15\n\nBudget: $300,000"

    result = weekly_update.decorate_weekly_update(
        old_md,
        updated_md,
        ["Main_Source"],
    )

    assert "<!-- weekly-update-banner:start -->" in result
    assert "## Weekly Update" in result
    assert "Deadline: April 15" in result
    assert '<span style="color: #c1121f;">Deadline: April 15</span>' in result
    assert "Budget: $300,000" in result
    assert '<span style="color: #c1121f;">Budget: $300,000</span>' not in result


def test_build_update_banner_summarizes_additions_and_sources() -> None:
    banner = weekly_update.build_update_banner(
        ["New data plan required"],
        ["Source_A"],
        run_date=date(2026, 4, 30),
    )

    assert "**Updated:** 2026-04-30" in banner
    assert "**Changed sources:** Source A" in banner
    assert "- New data plan required" in banner


def test_strip_weekly_update_markup_removes_generated_banner_and_spans() -> None:
    marked = (
        "<!-- weekly-update-banner:start -->\n"
        "## Weekly Update\n"
        "<!-- weekly-update-banner:end -->\n\n"
        '<span style="color: #c1121f;">Changed text</span>'
    )

    assert weekly_update.strip_weekly_update_markup(marked) == "Changed text"


def test_decorate_weekly_update_compares_against_previous_clean_run() -> None:
    previous_run = (
        "<!-- weekly-update-banner:start -->\n"
        "## Weekly Update\n"
        "<!-- weekly-update-banner:end -->\n\n"
        "# Guide\n\n"
        '<span style="color: #c1121f;">Deadline: April 15</span>\n'
        "Budget: $300,000"
    )
    next_run = "# Guide\n\nDeadline: May 20\nBudget: $300,000"

    result = weekly_update.decorate_weekly_update(
        previous_run,
        next_run,
        ["Main_Source"],
    )

    assert '<span style="color: #c1121f;">Deadline: May 20</span>' in result
    assert '<span style="color: #c1121f;">Budget: $300,000</span>' not in result


def test_decorate_weekly_update_omits_banner_when_guide_did_not_change() -> None:
    previous = "# Guide\n\nBudget: $300,000"
    result = weekly_update.decorate_weekly_update(
        previous,
        previous,
        ["Noisy_Source"],
    )

    assert "## Weekly Update" not in result
    assert "Noisy Source" not in result
    assert result == previous


def test_banner_summarizes_guide_changes_not_raw_source_noise() -> None:
    previous = "# Guide\n\nDeadline: March 1"
    updated = "# Guide\n\nDeadline: April 15"

    result = weekly_update.decorate_weekly_update(
        previous,
        updated,
        ["department_of_energy_genesis_mission_doe_genesis_manual_news"],
    )

    assert "Deadline: April 15" in result
    assert "Strategic Petroleum Reserve" not in result
    assert "News" in result


def test_summarize_source_changes_extracts_added_and_removed() -> None:
    diff_text = (
        "### Added/Modified Text\n\n"
        "  + Application Deadline: June 15, 2025\n"
        "  + New requirement: Data Management Plan required\n\n"
        "### Removed Text\n\n"
        "  - Application Deadline: March 1, 2025\n"
    )

    bullets = weekly_update.summarize_source_changes([("NIH_R15", diff_text)])

    assert any("June 15, 2025" in b for b in bullets)
    assert any("Data Management Plan" in b for b in bullets)
    assert any("Removed" in b and "March 1, 2025" in b for b in bullets)


def test_summarize_source_changes_deduplicates_and_caps_at_limit() -> None:
    diff_text = (
        "### Added/Modified Text\n\n"
        + "\n".join(f"  + Change number {i}" for i in range(20))
    )

    bullets = weekly_update.summarize_source_changes([("src", diff_text)], limit=5)

    assert len(bullets) <= 5


def test_summarize_source_changes_empty_diff_returns_empty() -> None:
    assert weekly_update.summarize_source_changes([("src", "")]) == []
    assert weekly_update.summarize_source_changes([]) == []


def test_decorate_weekly_update_with_source_diffs_shows_banner_even_when_guide_unchanged() -> None:
    guide = "# Guide\n\nBudget: $300,000"
    diff_text = (
        "### Added/Modified Text\n\n"
        "  + Budget ceiling raised to $500,000\n"
    )

    result = weekly_update.decorate_weekly_update(
        guide,
        guide,
        ["Funding_Source"],
        source_diffs=[("Funding_Source", diff_text)],
    )

    assert "## Weekly Update" in result
    assert "Budget ceiling raised" in result


def test_decorate_weekly_update_source_diffs_generic_bullet_when_diff_empty() -> None:
    guide = "# Guide\n\nBudget: $300,000"

    result = weekly_update.decorate_weekly_update(
        guide,
        guide,
        ["Source_A"],
        source_diffs=[("Source_A", "No meaningful changes detected.")],
    )

    assert "## Weekly Update" in result
    assert "up to date" in result.lower()


def test_decorate_weekly_update_no_source_diffs_still_omits_banner_when_unchanged() -> None:
    guide = "# Guide\n\nBudget: $300,000"

    result = weekly_update.decorate_weekly_update(
        guide,
        guide,
        ["Noisy_Source"],
    )

    assert "## Weekly Update" not in result
    assert result == guide
