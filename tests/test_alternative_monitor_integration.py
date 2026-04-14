import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.bootstrap_service import create_new_program
from src.services.review_service import finalize_review, save_review_decision


class AlternativeMonitorIntegrationTests(unittest.TestCase):
    @patch("src.services.bootstrap_service.persist_program")
    @patch("src.services.bootstrap_service.discover.build_alternative_funding_monitor")
    def test_monitor_sources_flow_into_finalize_with_metadata(
        self,
        mock_monitor_builder,
        mock_persist_program,
    ) -> None:
        mock_persist_program.return_value = {"ok": True, "enabled": False, "message": "Remote persistence disabled."}
        monitor_candidates = [
            {
                "label": "Wellcome Translational Awards",
                "url": "https://wellcome.org/grant-funding/schemes/translational-awards",
                "sections": ["Eligibility", "Key Dates"],
                "content_type": "text/html",
                "reachable": True,
                "funding_type": "international",
                "funder_name": "Wellcome Trust",
                "priority_score": 91,
                "confidence_score": 0.88,
            }
        ]
        monitor_sources = [
            {
                "name": "TestProgram_Wellcome_Translational_Awards",
                "url": "https://wellcome.org/grant-funding/schemes/translational-awards",
                "sections": ["Eligibility", "Key Dates"],
                "funding_type": "international",
                "funder_name": "Wellcome Trust",
                "priority_score": 91,
                "confidence_score": 0.88,
            }
        ]
        mock_monitor_builder.return_value = {"candidates": monitor_candidates, "sources": monitor_sources}

        with tempfile.TemporaryDirectory() as tmp_dir:
            cwd = Path.cwd()
            try:
                tmp_path = Path(tmp_dir)
                (tmp_path / "programs").mkdir(parents=True, exist_ok=True)
                os.chdir(tmp_path)
                created = create_new_program(
                    "Test Program",
                    enable_alternative_monitor=True,
                    monitor_sectors=["health"],
                    monitor_regions=["global"],
                )
                self.assertTrue(created["ok"])
                slug = created["slug"]

                source_name = monitor_sources[0]["name"]
                decision = save_review_decision(slug, source_name, "approved", "Looks relevant")
                self.assertTrue(decision["ok"])

                finalized = finalize_review(slug)
                self.assertTrue(finalized["ok"])
                sources_path = Path(finalized["sources_out"])
                self.assertTrue(sources_path.exists())

                written = json.loads(sources_path.read_text(encoding="utf-8"))
                self.assertEqual(len(written), 1)
                self.assertEqual(written[0]["funder_name"], "Wellcome Trust")
                self.assertEqual(written[0]["funding_type"], "international")
                self.assertEqual(written[0]["priority_score"], 91)
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
