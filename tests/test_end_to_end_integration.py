"""End-to-end integration test exercising the full workflow:

    bootstrap → review → generate → weekly update → audit log entry

All LLM and network calls are mocked so this runs without API keys.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

MOCK_GUIDE_MD = """\
# NIH R15 Sponsor Guide

## Executive Summary

The NIH R15 supports research at undergraduate-focused institutions.

## Program Overview

Small-scale research enhancement awards for eligible institutions.

## Key Dates

| Deadline | Date |
|----------|------|
| Application | March 1, 2025 |

## Eligibility

Undergraduate-focused institutions with < $6M NIH support.

## Award Size & Budget

Up to $300,000 in direct costs.

## How Proposals are Reviewed

Peer review through NIH study sections.

## Application Requirements

Standard NIH forms plus biosketch.

## Tips for Successful Proposals

Focus on student involvement and institutional impact.

## Resources

- [NIH R15 Page](https://grants.nih.gov/funding/activity-codes/R15)
"""

MOCK_UPDATED_GUIDE_MD = """\
# NIH R15 Sponsor Guide

## Executive Summary

The NIH R15 supports research at undergraduate-focused institutions.

## Program Overview

Small-scale research enhancement awards for eligible institutions.

## Key Dates

| Deadline | Date |
|----------|------|
| Application | June 15, 2025 |

## Eligibility

Undergraduate-focused institutions with < $6M NIH support.

## Award Size & Budget

Up to $300,000 in direct costs.

## How Proposals are Reviewed

Peer review through NIH study sections.

## Application Requirements

Standard NIH forms plus biosketch. Data Management Plan now required.

## Tips for Successful Proposals

Focus on student involvement and institutional impact.

## Resources

- [NIH R15 Page](https://grants.nih.gov/funding/activity-codes/R15)
"""

MOCK_SCRAPED_TEXT = """\
NIH R15 Research Enhancement Award
Application Deadline: March 1, 2025
Award Budget: Up to $300,000 in direct costs.
Eligible Institutions: Undergraduate-focused institutions.
"""

MOCK_SCRAPED_TEXT_UPDATED = """\
NIH R15 Research Enhancement Award
Application Deadline: June 15, 2025
Award Budget: Up to $300,000 in direct costs.
Eligible Institutions: Undergraduate-focused institutions.
New: Applicants must now include a Data Management and Sharing Plan.
"""


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace with a program directory."""
    programs_dir = tmp_path / "programs" / "test_nih_r15"
    programs_dir.mkdir(parents=True)

    sources = [
        {
            "name": "NIH_R15_Main",
            "url": "https://grants.nih.gov/funding/activity-codes/R15",
            "sections": ["Program Overview", "Eligibility"],
            "data_class": "public",
        }
    ]
    (programs_dir / "sources.json").write_text(json.dumps(sources, indent=2))

    original_cwd = Path.cwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(original_cwd)


def _mock_llm_chat(*args, **kwargs):
    """Return a mock LLM response that looks like OpenAI chat completion."""
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = MOCK_UPDATED_GUIDE_MD
    mock_response.choices = [mock_choice]
    return mock_response


def _mock_llm_chat_generate(*args, **kwargs):
    """Return a mock LLM response for guide generation."""
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = MOCK_GUIDE_MD
    mock_response.choices = [mock_choice]
    return mock_response


def _mock_llm_chat_citations(*args, **kwargs):
    """Return a mock LLM response for citation mapping."""
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps([
        {
            "claim": "Up to $300,000 in direct costs",
            "source_name": "NIH_R15_Main",
            "excerpt": "Award Budget: Up to $300,000 in direct costs.",
            "url": "https://grants.nih.gov/funding/activity-codes/R15",
        }
    ])
    mock_response.choices = [mock_choice]
    return mock_response


class TestEndToEndWorkflow:
    """Integration test covering bootstrap → review → generate → weekly update."""

    @patch("src.services.persistence_service.is_remote_enabled", return_value=False)
    @patch("scraper._fetch_with_retries")
    def test_full_pipeline_workflow(self, mock_fetch, mock_remote, workspace):
        """Exercise the complete workflow from source creation to weekly update."""
        import pipeline
        from src.services.review_service import (
            finalize_review,
            generate_first_draft,
            load_review_context,
            save_review_decision,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.text = f"<html><body><main>{MOCK_SCRAPED_TEXT}</main></body></html>"
        mock_fetch.return_value = mock_response

        slug = "test_nih_r15"

        # Step 1: Load review context
        context = load_review_context(slug)
        assert context["ok"], f"load_review_context failed: {context}"
        assert len(context["rows"]) == 1
        assert context["rows"][0]["name"] == "NIH_R15_Main"

        # Step 2: Approve the source
        decision = save_review_decision(slug, "NIH_R15_Main", "approved")
        assert decision["ok"], f"save_review_decision failed: {decision}"

        # Step 3: Finalize review
        finalized = finalize_review(slug, include_unreviewed=False)
        assert finalized["ok"], f"finalize_review failed: {finalized}"
        assert finalized["approved_count"] == 1

        # Step 4: Generate first draft (mocked LLM)
        mock_client = MagicMock()
        mock_client.chat.completions.create = _mock_llm_chat_generate
        with patch("generator.get_llm_client", return_value=mock_client):
            with patch("cite.add_citations", return_value=(MOCK_GUIDE_MD, [
                {"claim": "test claim", "source_name": "NIH_R15_Main", "url": "https://grants.nih.gov/funding/activity-codes/R15"}
            ])):
                result = generate_first_draft(slug, with_citations=True)

        assert result["ok"], f"generate_first_draft failed: {result}"
        assert result["draft_chars"] > 100

        draft_path = Path(result["draft_path"])
        assert draft_path.exists()
        draft_content = draft_path.read_text(encoding="utf-8")
        assert "NIH R15" in draft_content

        # Step 5: Promote draft to baseline
        from src.services.review_service import promote_draft_to_baseline
        promoted = promote_draft_to_baseline(slug)
        assert promoted["ok"], f"promote_draft_to_baseline failed: {promoted}"
        baseline_path = Path("programs") / slug / "guide.md"
        assert baseline_path.exists()

        # Step 6: Weekly update (simulating a source change)
        mock_response_updated = MagicMock()
        mock_response_updated.status_code = 200
        mock_response_updated.headers = {"Content-Type": "text/html"}
        mock_response_updated.text = f"<html><body><main>{MOCK_SCRAPED_TEXT_UPDATED}</main></body></html>"
        mock_fetch.return_value = mock_response_updated

        mock_client_update = MagicMock()
        mock_client_update.chat.completions.create = _mock_llm_chat
        with patch("updater.get_llm_client", return_value=mock_client_update):
            with patch("cite.add_citations", return_value=(MOCK_UPDATED_GUIDE_MD, [])):
                updated = pipeline.run_pipeline(
                    sources_config=str(Path("programs") / slug / "sources.json"),
                    guide_path=str(baseline_path),
                    output_dir=str(Path("programs") / slug / "output"),
                    state_file=str(Path("programs") / slug / "state.json"),
                    data_dir=str(Path("programs") / slug / "data"),
                )

        assert updated is True

        output_md = Path("programs") / slug / "output" / "sponsor_guide_updated.md"
        assert output_md.exists()
        final_content = output_md.read_text(encoding="utf-8")
        assert "June 15, 2025" in final_content or "Data Management" in final_content

    @patch("src.services.persistence_service.is_remote_enabled", return_value=False)
    def test_internal_pipeline_runs_without_llm(self, mock_remote, workspace):
        """Verify the internal pipeline works with template substitution only."""
        import internal_pipeline

        internal_sources = [
            {
                "name": "Internal_Budget_Data",
                "data_class": "internal",
                "template_fields": {
                    "section_title": "Internal Budget Guidelines",
                    "content": "Maximum indirect cost rate: 52%. Matching funds required for awards > $100K.",
                    "source_name": "Finance Office",
                },
            },
            {
                "name": "Internal_Compliance_Notes",
                "data_class": "internal",
                "template_fields": {
                    "section_title": "Compliance Requirements",
                    "content": "IRB approval required before submission. Export control review for international collaborations.",
                    "source_name": "Research Compliance",
                },
            },
        ]

        sources_path = workspace / "internal_sources.json"
        sources_path.write_text(json.dumps(internal_sources, indent=2))

        output_dir = workspace / "internal_output"
        result = internal_pipeline.run_internal_pipeline(
            sources_config=str(sources_path),
            output_dir=str(output_dir),
            program_name="Test NIH R15",
        )

        assert result is True
        output_file = output_dir / "sponsor_guide_internal_supplement.md"
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "Internal Budget Guidelines" in content
        assert "Compliance Requirements" in content
        assert "template substitution only" in content
        assert "52%" in content

    @patch("src.services.persistence_service.is_remote_enabled", return_value=False)
    @patch("scraper._fetch_with_retries")
    def test_content_zone_diffing_ignores_nav_changes(self, mock_fetch, mock_remote, workspace):
        """Verify that nav/footer changes don't trigger false positive updates."""
        import scraper

        slug = "test_nih_r15"
        state_file = str(Path("programs") / slug / "state.json")
        data_dir = str(Path("programs") / slug / "data")
        source = {
            "name": "NIH_R15_Main",
            "url": "https://grants.nih.gov/funding/activity-codes/R15",
            "data_class": "public",
        }

        page_v1 = """<html>
        <header><nav>Nav v1</nav></header>
        <body><main><p>Grant content stays the same.</p></main></body>
        <footer>Footer v1 - Copyright 2025</footer>
        </html>"""

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.text = page_v1
        mock_fetch.return_value = mock_response

        changed = scraper.check_for_updates_from_source(
            source, "NIH_R15_Main", state_file=state_file, data_dir=data_dir
        )
        assert changed is True  # First run always detects as new

        # Now change only the nav and footer
        page_v2 = """<html>
        <header><nav>Nav v2 - Updated Navigation</nav></header>
        <body><main><p>Grant content stays the same.</p></main></body>
        <footer>Footer v2 - Copyright 2026</footer>
        </html>"""

        mock_response.text = page_v2
        changed = scraper.check_for_updates_from_source(
            source, "NIH_R15_Main", state_file=state_file, data_dir=data_dir
        )
        assert changed is False  # Nav/footer changes should NOT trigger update

        # Now change the actual content
        page_v3 = """<html>
        <header><nav>Nav v2 - Updated Navigation</nav></header>
        <body><main><p>Grant content has been updated with new deadline.</p></main></body>
        <footer>Footer v2 - Copyright 2026</footer>
        </html>"""

        mock_response.text = page_v3
        changed = scraper.check_for_updates_from_source(
            source, "NIH_R15_Main", state_file=state_file, data_dir=data_dir
        )
        assert changed is True  # Real content change should trigger update
