import unittest
from unittest.mock import patch

import cite


def _mock_response_with_payload(payload: str):
    message = type("Message", (), {"content": payload})()
    choice = type("Choice", (), {"message": message})()
    return type("Response", (), {"choices": [choice]})()


class _MockCompletions:
    def __init__(self, payload: str):
        self._payload = payload

    def create(self, **kwargs):
        return _mock_response_with_payload(self._payload)


class _MockClient:
    def __init__(self, payload: str):
        self.chat = type(
            "Chat",
            (),
            {"completions": _MockCompletions(payload)},
        )()


class CiteGuardrailTests(unittest.TestCase):
    def test_tokenize_lowercases_deduplicates_and_keeps_min_length(self) -> None:
        tokens = cite._tokenize("NIH R01 R01 funds U.S. labs in 2026; AI + ML + data!")
        self.assertEqual(tokens, {"nih", "r01", "funds", "labs", "2026", "data"})

    def test_best_excerpt_and_link_returns_fragment_around_first_hit(self) -> None:
        claim = "The program supports clinical research in rural communities."
        source_text = (
            "Overview. This federal program supports clinical research in rural communities "
            "through dedicated grant mechanisms and technical assistance."
        )
        base_url = "https://example.org/program"

        excerpt, deep_link = cite._best_excerpt_and_link(claim, source_text, base_url)

        self.assertIn("supports clinical research in rural communities", excerpt.lower())
        self.assertTrue(deep_link.startswith(f"{base_url}#:~:text="))

    @patch("cite.assert_public_sources")
    @patch("cite.get_default_model", return_value="gemini-2.5-flash")
    @patch("cite.get_llm_client")
    def test_add_citations_rejects_source_when_overlap_is_below_six_percent(
        self,
        mock_get_client,
        _mock_get_default_model,
        _mock_assert_public_sources,
    ) -> None:
        # 17 claim tokens -> 1 overlap token yields 1/17 = 0.0588 (< 0.06), must fail.
        claim_line = (
            "alpha bravo charlie delta echo foxtrot golf hotel india juliet "
            "kilo lima mike november oscar papa shared"
        )
        guide_md = f"# Guide\n\n{claim_line}"
        sources = [{"name": "Source One", "url": "https://example.org/source-one"}]
        snapshots = {"Source One": "shared uniqueword"}
        llm_payload = '[{"id":"L2","sources":["Source One"]}]'

        mock_get_client.return_value = _MockClient(llm_payload)

        cited_md, evidence = cite.add_citations(guide_md, sources, snapshots, min_overlap=0.06)

        self.assertEqual(cited_md, guide_md)
        self.assertEqual(evidence, [])

    @patch("cite.assert_public_sources")
    @patch("cite.get_default_model", return_value="gemini-2.5-flash")
    @patch("cite.get_llm_client")
    def test_add_citations_accepts_source_when_overlap_meets_six_percent(
        self,
        mock_get_client,
        _mock_get_default_model,
        _mock_assert_public_sources,
    ) -> None:
        # 16 claim tokens -> 1 overlap token yields 1/16 = 0.0625 (>= 0.06), must pass.
        claim_line = (
            "alpha bravo charlie delta echo foxtrot golf hotel india juliet "
            "kilo lima mike november oscar shared"
        )
        guide_md = f"# Guide\n\n{claim_line}"
        sources = [{"name": "Source One", "url": "https://example.org/source-one"}]
        snapshots = {"Source One": "shared uniqueword"}
        llm_payload = '[{"id":"L2","sources":["Source One"]}]'

        mock_get_client.return_value = _MockClient(llm_payload)

        cited_md, evidence = cite.add_citations(guide_md, sources, snapshots, min_overlap=0.06)

        self.assertIn("[[1]](", cited_md)
        self.assertIn("## References", cited_md)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["line_id"], "L2")
        self.assertEqual(evidence[0]["sources"], ["Source One"])


if __name__ == "__main__":
    unittest.main()
