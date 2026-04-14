import unittest
from unittest.mock import patch

import discover


class DiscoverAlternativeMonitorTests(unittest.TestCase):
    def test_score_opportunity_prioritizes_relevant_new_sources(self) -> None:
        candidate = {
            "label": "Global Health Grant Opportunity",
            "url": "https://example.org/opportunities/global-health-grant",
            "sections": ["Eligibility", "Key Dates"],
            "focus_areas": ["global health"],
            "geography": "global",
            "source_authority": 0.95,
            "deadline": "2026-12-01",
        }
        priority, confidence = discover.score_opportunity(
            program="Global Health Innovation Program",
            candidate=candidate,
            sectors=["global health"],
            regions=["global"],
            tracked_urls={"https://already-tracked.org/item"},
        )
        self.assertGreaterEqual(priority, 80)
        self.assertGreaterEqual(confidence, 0.7)

    @patch("discover.validate_urls")
    @patch("discover.discover_sources")
    def test_build_alternative_funding_monitor_returns_ranked_sources(
        self,
        mock_discover_sources,
        mock_validate_urls,
    ) -> None:
        mock_discover_sources.return_value = [
            {
                "label": "Cancer Research Foundation Awards",
                "url": "https://example.org/foundation/cancer-awards",
                "sections": ["Eligibility", "Key Dates"],
            }
        ]
        mock_validate_urls.return_value = [
            {
                "label": "Cancer Research Foundation Awards",
                "url": "https://example.org/foundation/cancer-awards",
                "sections": ["Eligibility", "Key Dates"],
                "content_type": "text/html",
                "reachable": True,
            }
        ]

        payload = discover.build_alternative_funding_monitor(
            "Cancer Translational Science Program",
            sectors=["oncology"],
            regions=["US"],
        )
        self.assertEqual(len(payload["candidates"]), 1)
        self.assertEqual(len(payload["sources"]), 1)
        source = payload["sources"][0]
        self.assertIn("funding_type", source)
        self.assertIn("funder_name", source)
        self.assertIn("priority_score", source)
        self.assertIn("confidence_score", source)


if __name__ == "__main__":
    unittest.main()
