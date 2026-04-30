from datetime import date

import weekly_update


def test_decorate_weekly_update_adds_banner_and_highlights_changed_text() -> None:
    old_md = "# Guide\n\n## Key Dates\n\nDeadline: March 1\n\nBudget: $300,000"
    updated_md = "# Guide\n\n## Key Dates\n\nDeadline: April 15\n\nBudget: $300,000"
    diff = "### Added/Modified Text\n\n  + Deadline: April 15\n\n### Removed Text\n\n  - Deadline: March 1"

    result = weekly_update.decorate_weekly_update(
        old_md,
        updated_md,
        diff,
        ["Main_Source"],
    )

    assert "<!-- weekly-update-banner:start -->" in result
    assert "## Weekly Update" in result
    assert "Deadline: April 15" in result
    assert '<span style="color: #c1121f;">Deadline: April 15</span>' in result
    assert "Budget: $300,000" in result
    assert '<span style="color: #c1121f;">Budget: $300,000</span>' not in result


def test_build_update_banner_summarizes_additions_and_sources() -> None:
    diff = "### Added/Modified Text\n\n  + New data plan required"

    banner = weekly_update.build_update_banner(
        diff,
        ["Source_A"],
        run_date=date(2026, 4, 30),
    )

    assert "**Updated:** 2026-04-30" in banner
    assert "**Changed sources:** Source_A" in banner
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
        "### Added/Modified Text\n\n  + Deadline: May 20",
        ["Main_Source"],
    )

    assert '<span style="color: #c1121f;">Deadline: May 20</span>' in result
    assert '<span style="color: #c1121f;">Budget: $300,000</span>' not in result
