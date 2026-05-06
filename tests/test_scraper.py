import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import scraper


class _MockResponse:
    def __init__(
        self,
        text: str,
        status_code: int = 200,
        headers: Optional[dict] = None,
        content: Optional[bytes] = None,
    ) -> None:
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content if content is not None else text.encode("utf-8")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise scraper.requests.HTTPError(f"HTTP {self.status_code}")
        return None


class _MockResponseNoHeaders(_MockResponse):
    def __init__(self, text: str, status_code: int = 200, content: Optional[bytes] = None) -> None:
        super().__init__(text=text, status_code=status_code, headers={}, content=content)
        self.headers = None


class ScraperTests(unittest.TestCase):
    @patch("scraper.normalize_and_validate_public_url", side_effect=lambda url, context: url)
    @patch("scraper.time.sleep")
    @patch("scraper.random.uniform", return_value=0.0)
    @patch("scraper.requests.get")
    def test_fetch_and_clean_text_retries_429_then_succeeds(
        self,
        mock_get,
        _mock_uniform,
        mock_sleep,
        _mock_normalize,
    ) -> None:
        mock_get.side_effect = [
            _MockResponse("", status_code=429),
            _MockResponse("<html><body><p>ok</p></body></html>", status_code=200),
        ]

        text = scraper.fetch_and_clean_text("https://example.org/rate-limited")

        self.assertEqual(text, "ok")
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(2.0)

    @patch("scraper.normalize_and_validate_public_url", side_effect=lambda url, context: url)
    @patch("scraper.time.sleep")
    @patch("scraper.random.uniform", return_value=0.0)
    @patch("scraper.requests.get")
    def test_fetch_and_clean_text_honors_retry_after_header(
        self,
        mock_get,
        _mock_uniform,
        mock_sleep,
        _mock_normalize,
    ) -> None:
        mock_get.side_effect = [
            _MockResponse("", status_code=429, headers={"Retry-After": "5"}),
            _MockResponse("<html><body><p>ok</p></body></html>", status_code=200),
        ]

        text = scraper.fetch_and_clean_text("https://example.org/retry-after")

        self.assertEqual(text, "ok")
        self.assertEqual(mock_get.call_count, 2)
        self.assertGreaterEqual(mock_sleep.call_args[0][0], 5.0)

    @patch("scraper.normalize_and_validate_public_url", side_effect=lambda url, context: url)
    @patch("scraper.requests.get")
    def test_fetch_source_payload_handles_missing_response_headers(self, mock_get, _mock_normalize) -> None:
        mock_get.return_value = _MockResponseNoHeaders("<html><body><p>ok</p></body></html>")

        payload = scraper.fetch_source_payload("https://example.org/no-headers")

        self.assertEqual(payload["text"], "ok")
        self.assertEqual(payload["metadata"]["content_type"], "text/html")

    @patch("scraper.normalize_and_validate_public_url", side_effect=lambda url, context: url)
    @patch("scraper.time.sleep")
    @patch("scraper.random.uniform", return_value=0.0)
    @patch("scraper.requests.get", side_effect=scraper.requests.ConnectionError("offline"))
    def test_fetch_and_clean_text_connection_error_retries_then_raises(
        self,
        mock_get,
        _mock_uniform,
        mock_sleep,
        _mock_normalize,
    ) -> None:
        with self.assertRaises(scraper.requests.ConnectionError):
            scraper.fetch_and_clean_text("https://example.org/offline")

        self.assertEqual(mock_get.call_count, 4)
        self.assertEqual(mock_sleep.call_count, 3)
        self.assertEqual([call.args[0] for call in mock_sleep.call_args_list], [2.0, 4.0, 8.0])

    @patch("scraper.normalize_and_validate_public_url", side_effect=lambda url, context: url)
    @patch("scraper.requests.get")
    @patch("scraper._extract_pdf_text_with_pypdf", return_value=("PDF funding guidance", 12))
    def test_fetch_and_clean_text_supports_pdf_content_type(
        self,
        _mock_extract_pdf_text,
        mock_get,
        _mock_normalize,
    ) -> None:
        mock_get.return_value = _MockResponse(
            "%PDF-1.7",
            headers={"Content-Type": "application/pdf"},
            content=b"%PDF-1.7 fake bytes",
        )

        text = scraper.fetch_and_clean_text("https://example.org/notice")

        self.assertEqual(text, "PDF funding guidance")

    @patch("scraper.normalize_and_validate_public_url", side_effect=lambda url, context: url)
    @patch("scraper.requests.get")
    @patch("scraper._extract_pdf_text_with_pymupdf", return_value=("fallback text", 3))
    @patch("scraper._extract_pdf_text_with_pypdf", side_effect=RuntimeError("pypdf failed"))
    def test_fetch_source_payload_falls_back_to_pymupdf_when_pypdf_fails(
        self,
        _mock_pypdf,
        _mock_pymupdf,
        mock_get,
        _mock_normalize,
    ) -> None:
        mock_get.return_value = _MockResponse(
            "%PDF-1.7",
            headers={"Content-Type": "application/pdf"},
            content=b"%PDF-1.7 fake bytes",
        )

        payload = scraper.fetch_source_payload("https://example.org/notice.pdf")

        self.assertEqual(payload["text"], "fallback text")
        self.assertEqual(payload["metadata"]["extraction_method"], "pymupdf")
        self.assertEqual(payload["metadata"]["page_count"], 3)
        self.assertEqual(payload["metadata"]["character_count"], len("fallback text"))

    @patch(
        "scraper._extract_pdf_payload",
        return_value={
            "text": "uploaded pdf text",
            "metadata": {
                "extraction_method": "pypdf",
                "character_count": 17,
                "page_count": 1,
                "content_type": "application/pdf",
            },
        },
    )
    def test_fetch_source_payload_from_source_supports_local_pdf_file(self, _mock_extract_payload) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "uploaded.pdf"
            file_path.write_bytes(b"%PDF-1.7 fake bytes")

            payload = scraper.fetch_source_payload_from_source({"file_path": str(file_path)})

            self.assertEqual(payload["text"], "uploaded pdf text")
            self.assertEqual(payload["metadata"]["file_path"], str(file_path.resolve()))
            self.assertEqual(payload["metadata"]["extraction_method"], "pypdf")

    @patch(
        "scraper._extract_pdf_payload",
        return_value={
            "text": "uploaded pdf text",
            "metadata": {
                "extraction_method": "pypdf",
                "character_count": 17,
                "page_count": 1,
                "content_type": "application/pdf",
            },
        },
    )
    def test_fetch_source_payload_from_source_resolves_relative_path_from_repo_root(
        self, _mock_extract_payload
    ) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        app_dir = repo_root / "app"
        programs_dir = repo_root / "programs"
        with tempfile.TemporaryDirectory(dir=programs_dir) as tmp_dir:
            uploads_dir = Path(tmp_dir) / "review" / "uploads"
            uploads_dir.mkdir(parents=True)
            file_path = uploads_dir / "uploaded.pdf"
            file_path.write_bytes(b"%PDF-1.7 fake bytes")
            relative_file_path = str(file_path.relative_to(repo_root))

            old_cwd = Path.cwd()
            try:
                # Simulate Streamlit Cloud running with cwd at app/.
                os.chdir(app_dir)
                payload = scraper.fetch_source_payload_from_source({"file_path": relative_file_path})
            finally:
                os.chdir(old_cwd)

            self.assertEqual(payload["text"], "uploaded pdf text")
            self.assertEqual(payload["metadata"]["file_path"], str(file_path.resolve()))
            self.assertEqual(payload["metadata"]["extraction_method"], "pypdf")

    @patch("scraper.normalize_and_validate_public_url", side_effect=lambda url, context: url)
    @patch("scraper.requests.get")
    def test_fetch_and_clean_text_fallback_for_unscrapable_page(
        self,
        mock_get,
        _mock_normalize,
    ) -> None:
        html = """
        <html>
          <head><title>Access denied</title></head>
          <body>Please turn JavaScript on and reload the page.</body>
        </html>
        """
        mock_get.return_value = _MockResponse(html)

        text = scraper.fetch_and_clean_text("https://example.org/challenge")

        self.assertIn("Title: Access denied", text)
        self.assertIn("javascript", text.lower())

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
            self.assertIn("extraction", state["Source_A"])
            self.assertEqual(state["Source_A"]["extraction"]["extraction_method"], "html")

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
            expected_metadata = data_dir / "NIH_R15_2026_Opportunity__latest.meta.json"
            self.assertTrue(expected_snapshot.exists())
            self.assertTrue(expected_metadata.exists())


if __name__ == "__main__":
    unittest.main()
