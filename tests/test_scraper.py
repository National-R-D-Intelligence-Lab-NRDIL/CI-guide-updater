import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scraper


class _MockResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None


class ScraperTests(unittest.TestCase):
    @patch("scraper.normalize_and_validate_public_url", side_effect=lambda url, context: url)
    @patch("scraper.requests.get")
    def test_check_for_updates_compares_hash_and_returns_false_when_unchanged(
        self,
        mock_get,
        _mock_normalize,
    ) -> None:
        html = "<html><body><h1>NIH R15</h1><p>Deadline June 15.</p></body></html>"
        mock_get.return_value = _MockResponse(html)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            state_file = tmp_path / "state.json"
            data_dir = tmp_path / "data"

            first_changed = scraper.check_for_updates(
                "https://example.org/r15",
                "NIH_R15",
                state_file=str(state_file),
                data_dir=str(data_dir),
            )
            second_changed = scraper.check_for_updates(
                "https://example.org/r15",
                "NIH_R15",
                state_file=str(state_file),
                data_dir=str(data_dir),
            )

            self.assertTrue(first_changed)
            self.assertFalse(second_changed)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertIn("NIH_R15", state)
            self.assertEqual(state["NIH_R15"]["url"], "https://example.org/r15")

    @patch("scraper.normalize_and_validate_public_url", side_effect=lambda url, context: url)
    @patch("scraper.requests.get")
    def test_check_for_updates_creates_state_file_when_missing(
        self,
        mock_get,
        _mock_normalize,
    ) -> None:
        html = "<html><body><p>Initial snapshot content.</p></body></html>"
        mock_get.return_value = _MockResponse(html)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            state_file = tmp_path / "nested" / "state.json"
            data_dir = tmp_path / "data"

            changed = scraper.check_for_updates(
                "https://example.org/source",
                "Source_A",
                state_file=str(state_file),
                data_dir=str(data_dir),
            )

            self.assertTrue(changed)
            self.assertTrue(state_file.exists())

            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertIn("Source_A", state)
            self.assertIn("hash", state["Source_A"])
            self.assertIn("last_checked", state["Source_A"])

    @patch("scraper.normalize_and_validate_public_url", side_effect=lambda url, context: url)
    @patch("scraper.requests.get")
    def test_check_for_updates_sanitizes_snapshot_filename(
        self,
        mock_get,
        _mock_normalize,
    ) -> None:
        html = "<html><body><p>Funding guidance text.</p></body></html>"
        mock_get.return_value = _MockResponse(html)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            state_file = tmp_path / "state.json"
            data_dir = tmp_path / "snapshots"

            name = "NIH R15/2026:Opportunity?"
            changed = scraper.check_for_updates(
                "https://example.org/r15-opportunity",
                name,
                state_file=str(state_file),
                data_dir=str(data_dir),
            )

            self.assertTrue(changed)
            expected_snapshot = data_dir / "NIH_R15_2026_Opportunity__latest.txt"
            self.assertTrue(expected_snapshot.exists())


if __name__ == "__main__":
    unittest.main()
